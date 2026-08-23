"""交叉验证结果分析：把总分差异归因到具体判据。

核心纪律：只对「两边都测出结果」的判据做对比。任何一侧未测的，
既不算一致也不算分歧，单独列出——这正是 Nile 那份榜单最该修的地方。
"""

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
rs = json.load((HERE / "xval_results.json").open(encoding="utf-8"))

CRIT = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]
OFFICIAL_KEY = {
    "c1": "c1_ai_crawler", "c2": "c2_pdp_ssr", "c3": "c3_sitemap",
    "c4": "c4_product_schema", "c5": "c5_review_schema",
    "c6": "c6_faq_schema", "c7": "c7_org_schema",
}
NAME = {
    "c1": "AI 爬虫放行", "c2": "PDP 服务端渲染", "c3": "sitemap 新鲜度",
    "c4": "Product schema", "c5": "Review schema",
    "c6": "FAQPage/HowTo", "c7": "Organization",
}

complete = [r for r in rs if r["nile"].get("complete")]
partial = [r for r in rs if not r["nile"].get("complete")]

print("=" * 78)
print(f"样本：{len(rs)} 个品牌 · 七项全测出 {len(complete)} 个 · 未测全 {len(partial)} 个")
print("Nile 评分日期 2026-04-18 / 本次 2026-08-22，间隔约 4 个月")
print("=" * 78)

# ---------------------------------------------------------------- 总分分布
diffs = []
for r in complete:
    mine = r["nile"]["replicated_c1_c7"]
    off = r["nile_official"]["c1_c7"]
    diffs.append((r["brand"], off, mine, mine - off))

dist = Counter(d for _, _, _, d in diffs)
print("\n【总分差异分布】(复刻 C1-C7 减 官方 C1-C7)")
for d in sorted(dist, reverse=True):
    bar = "#" * dist[d]
    print(f"  {d:+3d}  {dist[d]:>3d}  {bar}")
hi = sum(v for k, v in dist.items() if k > 0)
eq = dist.get(0, 0)
lo = sum(v for k, v in dist.items() if k < 0)
print(f"  偏高 {hi} · 持平 {eq} · 偏低 {lo} · 均值 {sum(d for *_, d in diffs)/len(diffs):+.2f}")

# ---------------------------------------------------------------- 逐判据归因
print("\n【逐判据归因】只统计两边都测出的品牌")
print(f"  {'判据':<18} {'可比':>4} {'一致':>4} {'我过它不过':>10} {'它过我不过':>10} {'一致率':>7}")
print("  " + "-" * 62)
attrib = {}
for c in CRIT:
    agree = mine_only = theirs_only = 0
    for r in complete:
        m = r["nile"][c].get("pass")
        o = r["nile_official"].get(OFFICIAL_KEY[c])
        if m is None or o is None:
            continue
        if m == o:
            agree += 1
        elif m == 1:
            mine_only += 1
        else:
            theirs_only += 1
    n = agree + mine_only + theirs_only
    attrib[c] = (n, agree, mine_only, theirs_only)
    rate = f"{agree / n * 100:.0f}%" if n else "-"
    print(f"  {c.upper()} {NAME[c]:<14} {n:>4} {agree:>4} {mine_only:>10} "
          f"{theirs_only:>10} {rate:>7}")

net = {c: attrib[c][2] - attrib[c][3] for c in CRIT}
print("\n  对总分差异的净贡献（我过它不过 减 它过我不过）：")
for c, v in sorted(net.items(), key=lambda kv: -kv[1]):
    print(f"    {c.upper()} {NAME[c]:<16} {v:+3d}")
print(f"    {'合计':<19} {sum(net.values()):+3d}")

# ---------------------------------------------------------------- C3 专项
print("\n【C3 专项：时区 bug 的实测证据】")
c3_gap = [r for r in complete
          if r["nile"]["c3"].get("pass") == 1
          and r["nile_official"].get("c3_sitemap") == 0]
print(f"  官方判 fail、实测 pass 的品牌：{len(c3_gap)} 个")
tz_aware = [r for r in c3_gap
            if (r["nile"]["c3"].get("newest_lastmod") or "")[-6:].startswith(("+", "-"))]
print(f"  其中 lastmod 带非 UTC 时区偏移的：{len(tz_aware)} 个  ← 触发 naive/aware 比较崩溃的条件")
for r in c3_gap[:8]:
    c3 = r["nile"]["c3"]
    print(f"    {r['brand'][:22]:24s} lastmod={c3.get('newest_lastmod')} "
          f"age={c3.get('lastmod_age_days')}d products={c3.get('product_url_count')}")

# ---------------------------------------------------------------- 未测样本
print("\n【未测样本：Nile 记 0 分而实际是「测不到」】")
for r in partial:
    off = r["nile_official"]
    g = r["geolook"]
    print(f"  {r['brand'][:22]:24s} 官方总分={off['total_9']} "
          f"官方err={(off['fetch_error'] or '-')[:34]:36s} "
          f"实测首页={g.get('home_status')} 未测={','.join(r['unmeasured'])}")

# ---------------------------------------------------------------- geolook 独有层
print("\n【geolook 独有层：Nile 的 9 条判据完全看不到的部分】")
scored = [r for r in rs if r["geolook"].get("pdp_avg_score") is not None]
if scored:
    avg = sum(r["geolook"]["pdp_avg_score"] for r in scored) / len(scored)
    words = sum(r["geolook"]["pdp_avg_words"] for r in scored) / len(scored)
    q = sum(r["geolook"]["pdp_quotable"] for r in scored)
    sec = sum(r["geolook"]["pdp_sections"] for r in scored)
    print(f"  PDP 六维均分      {avg:.1f} / 100   （{len(scored)} 个品牌）")
    print(f"  PDP 平均词数      {words:.0f} 词      （1000 词是高影响力门槛）")
    print(f"  可引段落占比      {q} / {sec} = {q/max(sec,1)*100:.1f}%")
    zero_q = [r for r in scored if r["geolook"]["pdp_quotable"] == 0]
    print(f"  零可引段落品牌    {len(zero_q)} / {len(scored)}")
    grades = Counter(s["grade"] for r in scored for s in r["geolook"]["pdp_scores"])
    print(f"  PDP 评级分布      {dict(sorted(grades.items()))}")

print(f"\n  llms.txt 已上线   {sum(1 for r in rs if r['geolook'].get('llms_txt'))} / {len(rs)}")
waf = [r for r in rs if r["geolook"].get("waf_ua_blocked")]
rate = [r for r in rs if r["geolook"].get("waf_ua_rate_limited")]
print(f"  WAF 差异封锁      {len(waf)} 个  {[r['brand'] for r in waf]}")
print(f"  限速未测出        {len(rate)} 个  ← 修复前会被误报成 WAF 封锁")
rb = [r for r in rs if r["geolook"].get("robots_blocked_bots")]
print(f"  robots 封 AI 爬虫 {len(rb)} 个")
for r in rb[:6]:
    print(f"    {r['brand'][:22]:24s} {r['geolook']['robots_blocked_bots']}")
