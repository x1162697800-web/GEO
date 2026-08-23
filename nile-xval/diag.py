"""诊断上一轮全量跑的失败形态：区分「站点真实不可达」与「我方限流污染」。"""

import json
from collections import Counter
from pathlib import Path

rs = json.load(open(Path(__file__).parent / "xval_results.json", encoding="utf-8"))

print(f"{'brand':24s} {'home':>5s} {'fb':>5s} {'repl':>4s} {'off':>4s} {'sec':>6s}  error / waf")
print("-" * 104)
for r in rs:
    g = r["geolook"]
    err = str(g.get("home_error") or "")[:34]
    waf = ",".join(g.get("waf_ua_blocked") or [])[:28]
    print(f"{r['brand'][:23]:24s} "
          f"{str(g.get('home_status')):>5s} "
          f"{('Y' if g.get('home_ua_fallback') else '-'):>5s} "
          f"{str(r['nile'].get('replicated_c1_c7', '-')):>4s} "
          f"{r['nile_official']['total']:>4d} "
          f"{r['elapsed']:>6.1f}  {err} {waf}")

print()
print("home_status 分布:", dict(Counter(str(r["geolook"].get("home_status")) for r in rs)))
print("需要 UA 回退  :", sum(1 for r in rs if r["geolook"].get("home_ua_fallback")))
print("首页非 200    :", sum(1 for r in rs if r["geolook"].get("home_status") != 200))
print("WAF 差异封锁  :", sum(1 for r in rs if r["geolook"].get("waf_ua_blocked")))
print("复刻分为 0    :", sum(1 for r in rs if r["nile"].get("replicated_c1_c7") == 0))

# 关键对照：sitemap 能否取到商品 URL——取不到就说明整条链路被掐了
print()
print("sitemap 取到 0 个商品 URL 的品牌数:",
      sum(1 for r in rs if (r["nile"].get("c3") or {}).get("product_url_count") == 0))
print("PDP 成功抓到 3 个的品牌数:",
      sum(1 for r in rs if (r["nile"].get("c2") or {}).get("pdps_ok") == 3))
