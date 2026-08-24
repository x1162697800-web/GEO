"""从 D:/GEO 的同步历史里精确恢复被删的中日资产。

git log -- <path> 会把「删除该文件」的提交也列出来，所以不能直接拿最新那个
commit 去 checkout——要找最后一个**树里真的有这个文件**的提交。
"""

import subprocess
from pathlib import Path

GEO = Path("D:/GEO")
WANT = [
    "geolook/README.zh-CN.md",
    "geolook/README.ja.md",
    "geolook/docs/demo.ja.gif",
    "geolook/docs/demo.ja.mp4",
]


def git(*args, binary=False):
    return subprocess.run(["git", *args], cwd=GEO, capture_output=True,
                          text=not binary,
                          encoding=None if binary else "utf-8",
                          errors=None if binary else "replace")


for rel in WANT:
    r = git("log", "--all", "--format=%H", "--", rel)
    shas = [s for s in r.stdout.split() if s]
    found = None
    for sha in shas:                      # 新 → 旧
        chk = git("cat-file", "-e", f"{sha}:{rel}")
        if chk.returncode == 0:
            found = sha
            break
    if not found:
        print(f"[失败] {rel} — 所有候选提交的树里都没有它")
        continue
    out = git("show", f"{found}:{rel}", binary=True)
    if out.returncode != 0:
        print(f"[失败] {rel} — 读取内容出错")
        continue
    dst = GEO / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out.stdout)
    print(f"[恢复] {rel}  ({len(out.stdout)/1024:.1f} KB, 来自 {found[:7]})")

# 日文截图整目录
r = git("log", "--all", "--format=%H", "--", "geolook/docs/screenshots-ja")
for sha in [s for s in r.stdout.split() if s]:
    ls = git("ls-tree", "--name-only", f"{sha}:geolook/docs/screenshots-ja")
    if ls.returncode == 0 and ls.stdout.strip():
        names = ls.stdout.split()
        for n in names:
            out = git("show", f"{sha}:geolook/docs/screenshots-ja/{n}", binary=True)
            if out.returncode == 0:
                d = GEO / "geolook/docs/screenshots-ja"
                d.mkdir(parents=True, exist_ok=True)
                (d / n).write_bytes(out.stdout)
        print(f"[恢复] geolook/docs/screenshots-ja/  ({len(names)} 个文件, 来自 {sha[:7]})")
        break
else:
    print("[失败] screenshots-ja 目录")
