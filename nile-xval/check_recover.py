"""被删的中日资产还能不能从 D:/GEO 的自动同步历史里捞回来。"""

import subprocess
from pathlib import Path

GEO = Path("D:/GEO")
WANT = [
    "geolook/README.zh-CN.md",
    "geolook/README.ja.md",
    "geolook/docs/demo.gif",
    "geolook/docs/demo.mp4",
    "geolook/docs/screenshots/overview.png",
    "geolook/docs/screenshots-ja/overview.png",
]


def run(*args):
    return subprocess.run(["git", *args], cwd=GEO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


print("=== D:/GEO 历史区间 ===")
r = run("log", "--format=%h %ad %s", "--date=format:%H:%M:%S", "--reverse")
lines = [l for l in r.stdout.splitlines() if l.strip()]
print(f"  共 {len(lines)} 个提交")
if lines:
    print(f"  最早: {lines[0]}")
    print(f"  最新: {lines[-1]}")

print("\n=== 每个被删文件在历史里出现过吗 ===")
for rel in WANT:
    r = run("log", "--all", "--oneline", "--", rel)
    hits = [l for l in r.stdout.splitlines() if l.strip()]
    if hits:
        print(f"  [可恢复] {rel}  ({len(hits)} 个提交碰过它)")
        print(f"           最后一次: {hits[0]}")
    else:
        print(f"  [无记录] {rel}")

print("\n=== 现在磁盘上还剩什么 ===")
gl = GEO / "geolook"
for rel in ("README.md", "README.zh-CN.md", "README.ja.md"):
    print(f"  {'有' if (gl / rel).exists() else '无'}  {rel}")
docs = gl / "docs"
if docs.exists():
    print(f"  docs/ 目录: {sorted(p.name for p in docs.iterdir())}")

print("\n=== i18n 覆盖层是否还在（决定中文能否直接恢复）===")
ui = (gl / "scripts" / "ui.html").read_text("utf-8")
for token, label in [("UI_D={en:", "英文字典"), ("},ja:{", "日文字典"),
                     ("const UI_SUB", "词元替换表"), ("const UI_RX", "正则表"),
                     ("function uiTranslate", "翻译函数"),
                     ("const ULANG='en'", "语言被写死为 en")]:
    print(f"  {'在' if token in ui else '不在'}  {label}")
print("\n  → 中文是 ui.html 的源语言，覆盖层还在，"
      "所以恢复中文只需解开写死的 ULANG 并把切换器加回来。")
