"""改名前的勘察：列出 GeoLook 的所有书写形态与所在位置，区分「产品名」和「不能动的东西」。

不能动的三类：
  * 域名 geolook.cc / 仓库 aigclink/geolook / ProductHunt 链接——新域名没买之前改了就是死链
  * work/ 与 .jobs/ 下的项目数据（geolook 是测试项目的 slug，不是产品名）
  * 测试夹具里的假品牌名（改不改都行，但要知道它是数据不是品牌）
"""

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "geolook"
SKIP_DIRS = {".git", "work", ".jobs", "__pycache__", "node_modules"}
EXTS = {".md", ".py", ".html", ".js", ".json", ".sh", ".txt", ".yml", ".yaml"}

# 含 URL / 仓库 / 域名的行——这些先别动
PROTECTED = re.compile(r"geolook\.cc|github\.com/[\w-]+/geolook|producthunt\.com|"
                       r"products/geolook|badge-geolook", re.I)

variants = Counter()
protected_lines = []
files = Counter()

for p in sorted(ROOT.rglob("*")):
    if not p.is_file() or p.suffix.lower() not in EXTS:
        continue
    if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
        continue
    try:
        text = p.read_text("utf-8")
    except (UnicodeDecodeError, PermissionError):
        continue
    rel = str(p.relative_to(ROOT))
    for i, line in enumerate(text.split("\n"), 1):
        for m in re.finditer(r"[Gg][Ee][Oo][*_]*[Ll][Oo][Oo][Kk]", line):
            variants[m.group(0)] += 1
            files[rel] += 1
            if PROTECTED.search(line):
                protected_lines.append((rel, i, line.strip()[:100]))

print("=== 书写形态 ===")
for v, n in variants.most_common():
    print(f"  {n:>4}  {v}")
print(f"\n合计 {sum(variants.values())} 处 / {len(files)} 个文件")

print("\n=== 按文件 ===")
for f, n in files.most_common():
    print(f"  {n:>4}  {f}")

print(f"\n=== 受保护（含域名/仓库/PH 链接，本批不动）：{len(protected_lines)} 行 ===")
seen = set()
for rel, i, line in protected_lines:
    key = (rel, line[:50])
    if key in seen:
        continue
    seen.add(key)
    print(f"  {rel}:{i}")
    print(f"      {line}")
