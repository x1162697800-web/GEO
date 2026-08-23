"""GeoLook → Grounded 改名。

保护三类不能动的东西（新域名/新仓库还不存在，改了就是死链）：
  geolook.cc · github.com/aigclink/geolook · producthunt 的 products/geolook 与 badge-geolook

做法是先把受保护片段替换成哨兵、改名、再还原——比逐行判断可靠。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "geolook"
SKIP_DIRS = {".git", "work", ".jobs", "__pycache__", "node_modules"}
EXTS = {".md", ".py", ".html", ".js", ".json", ".sh", ".txt", ".yml", ".yaml"}

PROTECT = [
    ("geolook.cc", "\x00D\x00"),
    ("aigclink/geolook", "\x00R\x00"),
    ("products/geolook", "\x00P\x00"),
    ("badge-geolook", "\x00B\x00"),
]

# 顺序有讲究：先长后短、先特殊后一般，否则 Geo**Look 会被 GeoLook 规则劈开
RENAMES = [
    ("Geo**Look", "Grounded"),      # README 标题里的 markdown 加粗写法
    ("GEOLOOK", "GROUNDED"),        # 环境变量前缀 GEOLOOK_TOKEN / GEOLOOK_HOST
    ("GeoLook", "Grounded"),
    ("Geolook", "Grounded"),        # X-Geolook-Token 这类
    ("geolook", "grounded"),        # slug、mcpServers 键、CLI 提示
]

apply = "--apply" in sys.argv
changed = []

for p in sorted(ROOT.rglob("*")):
    if not p.is_file() or p.suffix.lower() not in EXTS:
        continue
    if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
        continue
    try:
        text = original = p.read_text("utf-8")
    except (UnicodeDecodeError, PermissionError):
        continue

    for real, token in PROTECT:
        text = text.replace(real, token)
    for old, new in RENAMES:
        text = text.replace(old, new)
    for real, token in PROTECT:
        text = text.replace(token, real)

    if text != original:
        n = sum(1 for a, b in zip(original.split("\n"), text.split("\n")) if a != b)
        changed.append((str(p.relative_to(ROOT)), n))
        if apply:
            p.write_text(text, "utf-8")

print(("已改写" if apply else "将改写") + f" {len(changed)} 个文件：")
for f, n in sorted(changed, key=lambda x: -x[1]):
    print(f"  {n:>4} 行  {f}")
if not apply:
    print("\n（预演。加 --apply 实际写入）")
