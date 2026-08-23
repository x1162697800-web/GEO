"""Nile Readiness Index (Edition 1) 与 geolook 审计口径的交叉验证。

对同一批品牌站同时跑两套判据：
  - 复刻 Nile 的 C1-C7（robots / SSR / sitemap / Product / Review / FAQ / Organization）
  - 调用 geolook 自身的函数（RFC 9309 robots 判定、analyze_page、score_page、UA 差异探测）

纪律（第一轮跑批的教训）：
  1. 串行 + 品牌间隔，绝不用并发把目标站打进限流——429 会让整批数据不可用
  2. 429/503 指数退避重试；重试仍失败的判据记 None（未测），**绝不记 0**
     「抓取失败」和「判据不通过」是两件事，混为一谈正是 Nile 那份榜单的核心缺陷
  3. 与官方分对比只比同口径的 C1-C7，不拿它的 9 项总分比

geolook 仓库零改动：fcntl 只在 project_lock 里用到，本脚本不碰项目目录，
所以 import 之前塞一个 no-op 替身即可在 Windows 上复用其全部逻辑。
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
GEOLOOK_SCRIPTS = HERE.parent / "geolook" / "scripts"

if "fcntl" not in sys.modules:
    try:
        import fcntl  # noqa: F401
    except ModuleNotFoundError:
        stub = types.ModuleType("fcntl")
        stub.LOCK_EX, stub.LOCK_SH, stub.LOCK_UN, stub.LOCK_NB = 2, 1, 8, 4
        stub.flock = lambda fd, op: None
        sys.modules["fcntl"] = stub

sys.path.insert(0, str(GEOLOOK_SCRIPTS))

import audit  # noqa: E402
import crawl  # noqa: E402
import geolib as G  # noqa: E402

# ---------------------------------------------------------------- 口径常量

NILE_C1_BOTS = ["GPTBot", "PerplexityBot", "ClaudeBot", "Google-Extended",
                "Amazonbot", "CCBot", "FacebookBot"]
NILE_C1_THRESHOLD = 4
SITEMAP_FRESH_DAYS = 90
PDP_SAMPLE = 3
FAQ_CANDIDATE_PATHS = ["/pages/faq", "/pages/faqs", "/pages/about"]

# 速率纪律
RATE_STATUS = (429, 503)
BACKOFF = (3, 8, 20)      # 撞限流后的退避秒数
PAGE_DELAY = 0.8          # 同一站点内两次请求的间隔
BRAND_DELAY = 2.5         # 品牌之间的间隔

PRICE_RX = re.compile(r"[$€£¥]\s?\d[\d,.]*")
LASTMOD_RX = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>", re.I)
LOC_RX = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)


def log(msg: str):
    print(msg, flush=True)


# ---------------------------------------------------------------- 限流韧性抓取


class RateLimited(Exception):
    """退避重试后仍被限流：调用方必须把相关判据记为「未测」，不能记 0。"""


def fetch_resilient(url: str, timeout: int = 15) -> dict:
    """撞上 429/503 就指数退避重试；耗尽退避仍被限流则抛 RateLimited。"""
    res = G.fetch(url, timeout=timeout, retries=0)
    for wait in BACKOFF:
        if res["status"] not in RATE_STATUS:
            return res
        log(f"      限流 {res['status']}，退避 {wait}s 重试：{url}")
        time.sleep(wait)
        res = G.fetch(url, timeout=timeout, retries=0)
    if res["status"] in RATE_STATUS:
        raise RateLimited(f"HTTP {res['status']} after backoff: {url}")
    return res


def fetch_text_resilient(url: str) -> str:
    for i, wait in enumerate((0,) + BACKOFF):
        if wait:
            time.sleep(wait)
        txt = G.fetch_text(url)
        if txt:
            return txt
    return ""


# ---------------------------------------------------------------- JSON-LD 工具


def walk_jsonld(node, out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        out.append(node)
        for v in node.values():
            walk_jsonld(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_jsonld(v, out)
    return out


def types_of(obj: dict) -> set[str]:
    t = obj.get("@type") or obj.get("type") or []
    if isinstance(t, str):
        t = [t]
    return {str(x).split("/")[-1] for x in t if x}


def find_type(blocks, wanted: str) -> list[dict]:
    return [o for o in walk_jsonld(blocks) if wanted in types_of(o)]


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def has_value(obj: dict, key: str) -> bool:
    v = obj.get(key)
    if v is None:
        return False
    if isinstance(v, (list, dict)):
        return bool(v)
    return bool(str(v).strip())


# ---------------------------------------------------------------- Nile C1-C7 复刻


def nile_c1(robots_txt: str, fetched: bool) -> dict:
    if not fetched:
        return {"pass": None, "note": "robots.txt 未取到"}
    groups = G.robots_parse(robots_txt)
    allowed, blocked, rules = [], [], {}
    for bot in NILE_C1_BOTS:
        ok, rule = G.robots_decision(groups, bot, "/")
        (allowed if ok else blocked).append(bot)
        if rule:
            rules[bot] = rule
    return {"pass": int(len(allowed) >= NILE_C1_THRESHOLD),
            "allowed": allowed, "blocked": blocked, "rules": rules}


def parse_lastmod(raw: str) -> datetime | None:
    """三种常见 lastmod 写法都吃下，且一律归一成 tz-aware UTC。
    Nile 的 scorer 恰恰在 offset-naive/aware 比较上崩了。"""
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def nile_c3(root: str, robots_txt: str) -> dict:
    """C3：sitemap 存在、合法 XML、含商品 URL、且有 90 天内的 lastmod。"""
    queue = [G.normalize_url(root, "/sitemap.xml"), G.normalize_url(root, "/sitemap_index.xml")]
    for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt or ""):
        queue.append(m.strip())

    seen, product_urls, all_urls = set(), [], []
    newest, xml_valid = None, False
    while queue and len(seen) < 6:
        sm = queue.pop(0)
        if not sm or sm in seen:
            continue
        seen.add(sm)
        xml = fetch_text_resilient(sm)
        if not xml or "<" not in xml:
            continue
        if "<urlset" in xml or "<sitemapindex" in xml:
            xml_valid = True
        for raw in LASTMOD_RX.findall(xml):
            dt = parse_lastmod(raw)
            if dt and (newest is None or dt > newest):
                newest = dt
        locs = LOC_RX.findall(xml)
        if "<sitemapindex" in xml:
            prod = [u for u in locs if "product" in u.lower()]
            queue = prod + queue + [u for u in locs if u not in prod][:3]
        else:
            all_urls.extend(locs)
            product_urls.extend(u for u in locs if "/products/" in u.lower())
        time.sleep(PAGE_DELAY)

    age = None if newest is None else (datetime.now(timezone.utc) - newest).days
    fresh = age is not None and age <= SITEMAP_FRESH_DAYS
    return {"pass": int(bool(xml_valid and product_urls and fresh)),
            "xml_valid": xml_valid, "product_url_count": len(product_urls),
            "total_url_count": len(all_urls),
            "newest_lastmod": newest.isoformat() if newest else None,
            "lastmod_age_days": age, "maps_seen": sorted(seen),
            "_product_urls": product_urls}


def check_pdp(page: dict) -> dict:
    blocks = page.get("jsonld_raw")
    text = page.get("text") or ""
    products = find_type(blocks, "Product")

    has_title = bool((page.get("title") or "").strip() or page.get("h1"))
    price_in_ld = any(isinstance(o, dict) and has_value(o, "price")
                      for p in products for o in as_list(p.get("offers")))
    has_price = price_in_ld or bool(PRICE_RX.search(text))
    has_desc = page.get("word_count", 0) >= 50 or any(
        has_value(p, "description") for p in products)
    c2 = int(has_title and has_price and has_desc)

    c4, c4_missing = 0, []
    for p in products:
        missing = [k for k in ("name", "image", "brand") if not has_value(p, k)]
        if not any(isinstance(o, dict) and has_value(o, "price") and has_value(o, "availability")
                   for o in as_list(p.get("offers"))):
            missing.append("offers.price+availability")
        if not any(has_value(p, k) for k in ("gtin", "gtin8", "gtin12", "gtin13",
                                             "gtin14", "mpn", "sku")):
            missing.append("gtin|mpn|sku")
        if not missing:
            c4, c4_missing = 1, []
            break
        c4_missing = missing

    c5 = 0
    for obj in walk_jsonld(blocks):
        t = types_of(obj)
        if "AggregateRating" in t:
            try:
                cnt = float(str(obj.get("reviewCount") or obj.get("ratingCount") or 0)
                            .replace(",", ""))
            except ValueError:
                cnt = 0
            if cnt > 0 and has_value(obj, "ratingValue"):
                c5 = 1
        if "Review" in t and has_value(obj, "reviewRating"):
            c5 = 1

    return {"c2": c2, "c4": c4, "c5": c5, "c4_missing": c4_missing,
            "product_ld": len(products), "has_price": has_price,
            "has_title": has_title, "has_desc": has_desc}


def nile_c6(root: str, home: dict) -> dict:
    if {"FAQPage", "HowTo"} & set(home.get("jsonld_types") or []):
        return {"pass": 1, "hits": [root], "checked": [root]}
    checked = [root]
    for path in FAQ_CANDIDATE_PATHS:
        url = urljoin(root, path)
        checked.append(url)
        try:
            res = fetch_resilient(url, timeout=12)
        except RateLimited:
            return {"pass": None, "note": "限流未测", "checked": checked}
        if res["status"] == 200 and res["html"]:
            pg = crawl.analyze_page(url, res)
            if {"FAQPage", "HowTo"} & set(pg.get("jsonld_types") or []):
                return {"pass": 1, "hits": [url], "checked": checked}
        time.sleep(PAGE_DELAY)
    return {"pass": 0, "hits": [], "checked": checked}


def nile_c7(home: dict) -> dict:
    orgs = find_type(home.get("jsonld_raw"), "Organization")
    same_as = 0
    for o in orgs:
        n = len(as_list(o.get("sameAs")))
        if has_value(o, "name") and has_value(o, "url") and n >= 2:
            return {"pass": 1, "org_blocks": len(orgs), "same_as_count": n}
        same_as = max(same_as, n)
    return {"pass": 0, "org_blocks": len(orgs), "same_as_count": same_as}


# ---------------------------------------------------------------- 单品牌流程


def run_brand(row: dict) -> dict:
    brand, root = row["brand"], row["url"].rstrip("/")
    out: dict = {"brand": brand, "url": root, "nile": {}, "geolook": {},
                 "unmeasured": [], "errors": []}
    t0 = time.time()

    try:
        robots_txt = fetch_text_resilient(G.normalize_url(root, "/robots.txt"))
        time.sleep(PAGE_DELAY)

        home_res = fetch_resilient(root, timeout=20)
        home = crawl.analyze_page(root, home_res) if home_res["html"] else {}
        out["geolook"].update({
            "home_status": home_res["status"],
            "home_ua_fallback": bool(home_res.get("ua_fallback")),
            "home_error": home_res.get("error"),
        })
        time.sleep(PAGE_DELAY)

        c1 = nile_c1(robots_txt, bool(robots_txt))
        c3 = nile_c3(root, robots_txt)
        product_urls = c3.pop("_product_urls")

        # PDP 等距抽样（可复现；Nile 用的是随机 3 个）
        pdp_urls = []
        if product_urls:
            uniq = sorted(dict.fromkeys(product_urls))
            step = max(1, len(uniq) // PDP_SAMPLE)
            pdp_urls = [uniq[i * step] for i in range(PDP_SAMPLE) if i * step < len(uniq)]
        if not pdp_urls:
            js = fetch_text_resilient(G.normalize_url(root, "/products.json?limit=6"))
            try:
                handles = [p["handle"] for p in json.loads(js).get("products", [])]
                pdp_urls = [urljoin(root + "/", f"products/{h}") for h in handles[:PDP_SAMPLE]]
            except Exception:  # noqa: BLE001
                pdp_urls = []

        pdp_checks, pdp_scores, pdp_rate_limited = [], [], False
        for u in pdp_urls:
            try:
                res = fetch_resilient(u, timeout=20)
            except RateLimited as e:
                pdp_rate_limited = True
                pdp_checks.append({"url": u, "rate_limited": True, "note": str(e)})
                break
            if not res["html"]:
                pdp_checks.append({"url": u, "status": res["status"], "error": res.get("error")})
                continue
            pg = crawl.analyze_page(u, res)
            chk = check_pdp(pg)
            chk["url"] = u
            pdp_checks.append(chk)
            pdp_scores.append(audit.score_page(pg, []))
            time.sleep(PAGE_DELAY)

        ok = [c for c in pdp_checks if "c2" in c]
        # 取不满 3 个 PDP 就无法用 Nile 的「3/3 才算过」判据 → 记未测，不记 0
        if pdp_rate_limited or len(ok) < PDP_SAMPLE:
            c2 = c4 = c5 = None
            out["unmeasured"] += ["c2", "c4", "c5"]
        else:
            c2 = int(all(c["c2"] for c in ok))
            c4 = int(all(c["c4"] for c in ok))
            c5 = int(all(c["c5"] for c in ok))

        if home:
            c6, c7 = nile_c6(root, home), nile_c7(home)
        else:
            c6, c7 = {"pass": None, "note": "首页未取到"}, {"pass": None, "note": "首页未取到"}

        crit = {"c1": c1, "c2": {"pass": c2, "pdps_ok": len(ok)}, "c3": c3,
                "c4": {"pass": c4}, "c5": {"pass": c5}, "c6": c6, "c7": c7}
        for k, v in crit.items():
            if v.get("pass") is None and k not in out["unmeasured"]:
                out["unmeasured"].append(k)
        scored = [v["pass"] for v in crit.values() if v.get("pass") is not None]

        out["nile"] = {
            **crit, "pdp_urls": pdp_urls, "pdp_detail": pdp_checks,
            "replicated_c1_c7": sum(scored),
            "criteria_measured": len(scored),
            "complete": len(scored) == 7,
        }

        # geolook 独有层
        blocked, partial = crawl.check_robots(
            robots_txt, [urlparse(u).path for u in pdp_urls] or ["/"])
        probe, ua_blocked, ua_rate = ({}, [], [])
        if home:
            probe, ua_blocked, ua_rate = crawl.probe_ai_ua(root, home, robots_txt, delay=1.0)

        llms_txt = fetch_text_resilient(G.normalize_url(root, "/llms.txt"))
        out["geolook"].update({
            "robots_blocked_bots": blocked,
            "robots_partial": partial,
            "ua_probe": probe,
            "waf_ua_blocked": ua_blocked,
            "waf_ua_rate_limited": ua_rate,
            "llms_txt": bool(llms_txt),
            "x_robots_noindex": "noindex" in (home_res.get("x_robots_tag") or "").lower(),
            "home_score": audit.score_page(home, []) if home else None,
            "pdp_scores": pdp_scores,
            "pdp_avg_score": (round(sum(s["score"] for s in pdp_scores) / len(pdp_scores), 1)
                              if pdp_scores else None),
            "pdp_avg_words": (round(sum(s["word_count"] for s in pdp_scores) / len(pdp_scores))
                              if pdp_scores else None),
            "pdp_quotable": sum(s["sections_quotable"] for s in pdp_scores) if pdp_scores else None,
            "pdp_sections": sum(s["sections_total"] for s in pdp_scores) if pdp_scores else None,
        })
    except RateLimited as e:
        out["errors"].append(f"RateLimited: {e}")
        out["unmeasured"] = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"{type(e).__name__}: {e}")

    out["elapsed"] = round(time.time() - t0, 1)
    return out


def nile_official_c1_c7(row: dict) -> int:
    return sum(int(row[k]) for k in (
        "c1_ai_crawler", "c2_pdp_ssr", "c3_sitemap", "c4_product_schema",
        "c5_review_schema", "c6_faq_schema", "c7_org_schema"))


def main():
    rows = list(csv.DictReader((HERE / "nile_scores.csv").open(encoding="utf-8")))
    log(f"读入 {len(rows)} 个品牌 · 串行 + 退避重试 · 品牌间隔 {BRAND_DELAY}s")
    log(f"{'brand':24s} {'off':>4s} {'repl':>5s} {'meas':>5s} {'sec':>6s}  note")
    log("-" * 82)

    results = []
    out_path = HERE / "xval_results.json"
    for i, row in enumerate(rows, 1):
        res = run_brand(row)
        official = nile_official_c1_c7(row)
        res["nile_official"] = {
            "total_9": int(row["total"]),
            "c1_c7": official,
            **{k: int(row[k]) for k in row if k.startswith("c") and row[k] in ("0", "1")},
            "fetch_error": row["fetch_error"],
        }
        n = res["nile"]
        repl = n.get("replicated_c1_c7")
        meas = n.get("criteria_measured", 0)
        note = ""
        if res["errors"]:
            note = res["errors"][0][:38]
        elif res["unmeasured"]:
            note = "未测: " + ",".join(res["unmeasured"])
        elif repl is not None:
            note = f"差 {repl - official:+d}"
        log(f"{res['brand'][:23]:24s} {official:>4d} "
            f"{str(repl):>5s} {meas:>3d}/7 {res['elapsed']:>6.1f}  {note}")

        results.append(res)
        G.write_json(out_path, results)
        if i < len(rows):
            time.sleep(BRAND_DELAY)

    log(f"\n完成 {len(results)} 条 → {out_path}")


if __name__ == "__main__":
    main()
