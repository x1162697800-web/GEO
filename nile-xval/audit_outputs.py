"""跑通 ≠ 产物正确。逐个检查交付物里有没有空洞、占位符、明显错误。"""

import json
import re
from pathlib import Path

P = Path("D:/GEO/geolook/work/geolook")

print("=== 产物清单 ===")
for sub in ("assets", "reports", "delivery", "deliverables", "content"):
    d = P / sub
    if not d.exists():
        print(f"  [缺] {sub}/")
        continue
    files = sorted(f for f in d.rglob("*") if f.is_file())
    print(f"  {sub}/  {len(files)} 个文件")

print("\n=== 六个编译目标是否都产出 ===")
adir = P / "assets"
targets = {
    "llms.txt": adir / "llms.txt",
    "llms.en.txt": adir / "llms.en.txt",
    "jsonld/": adir / "jsonld",
    "snippets/": adir / "snippets",
    "outlines/": adir / "outlines",
    "attribution/": adir / "attribution",
    "skill/SKILL.md": adir / "skill" / "SKILL.md",
    "skill/SKILL.en.md": adir / "skill" / "SKILL.en.md",
}
for name, p in targets.items():
    if not p.exists():
        print(f"  [缺] {name}")
    elif p.is_dir():
        print(f"  [有] {name}  {len(list(p.iterdir()))} 个文件")
    else:
        print(f"  [有] {name}  {p.stat().st_size} B")

print("\n=== 占位符 / 未填内容扫描 ===")
BAD = ["待确认", "待补", "TODO", "TBD", "（空）", "undefined", "None", "null,"]
for f in sorted(adir.rglob("*")):
    if not f.is_file() or f.suffix not in (".txt", ".md", ".json", ".html", ".sh"):
        continue
    t = f.read_text("utf-8", "ignore")
    hits = [b for b in BAD if b in t]
    if hits:
        print(f"  {f.relative_to(adir)}: {hits}")

print("\n=== llms.txt 内容 ===")
llms = adir / "llms.txt"
if llms.exists():
    print("  " + "\n  ".join(llms.read_text("utf-8").split("\n")[:16]))

print("\n=== JSON-LD 是否合法且字段齐全 ===")
for f in sorted((adir / "jsonld").glob("*.json")) if (adir / "jsonld").exists() else []:
    try:
        o = json.loads(f.read_text("utf-8"))
    except json.JSONDecodeError as e:
        print(f"  [坏] {f.name}: {e}")
        continue
    empty = [k for k, v in o.items() if v in ("", [], {}, None)]
    print(f"  [OK] {f.name}  @type={o.get('@type')}" + (f"  空字段={empty}" if empty else ""))

print("\n=== 报告与交付包 ===")
for d in ("reports", "delivery"):
    for sub in sorted((P / d).iterdir()) if (P / d).exists() else []:
        files = sorted(x.name for x in sub.rglob("*") if x.is_file())
        print(f"  {d}/{sub.name}: {files}")
