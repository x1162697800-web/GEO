"""核对三语 README：改名是否干净、新定位章节是否都在、语言互链是否完整。"""

import re
from pathlib import Path

GL = Path("D:/GEO/geolook")
PROTECT = re.compile(r"geolook\.cc|aigclink/geolook|products/geolook|badge-geolook")

FILES = ["README.md", "README.zh-CN.md", "README.ja.md"]
MARKS = [
    ("六个编译目标", r"six deploy targets|六个部署目标|六つのデプロイ対象|six targets"),
    ("SKILL.md 部署目标", r"`SKILL\.md`"),
    ("MCP server", r"MCP"),
    ("第二对比轴", r"agentic commerce backends|agentic commerce 后端|エージェンティックコマース基盤"),
]

for f in FILES:
    p = GL / f
    if not p.exists():
        print(f"{f}: 不存在")
        continue
    t = p.read_text("utf-8")
    stray = [m.group(0) for m in re.finditer(r"(?i)geolook", t)
             if not PROTECT.search(t[max(0, m.start() - 40):m.end() + 40])]
    print(f"\n=== {f} ({len(t)/1024:.1f} KB) ===")
    print(f"  Grounded 出现      : {len(re.findall('Grounded', t))} 次")
    print(f"  未保护的旧品牌名   : {len(stray)} 处 {'← 需修' if stray else ''}")
    for label, pat in MARKS:
        print(f"  {label:<18}: {'有' if re.search(pat, t) else '缺'}")
    langs = re.search(r"\[English\]|English ·|简体中文|日本語", t)
    print(f"  语言互链           : {'有' if langs else '缺'}")

print("\n=== docs 资产 ===")
docs = GL / "docs"
print(f"  {sorted(p.name for p in docs.iterdir())}")
for d in ("screenshots", "screenshots-ja"):
    sub = docs / d
    print(f"  {d}: {len(list(sub.iterdir())) if sub.exists() else '不存在'} 个文件")
