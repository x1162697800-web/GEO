"""交付门禁检查：先查会泄密的，再查会让用户装不上/跑不通的，最后查文档一致性。"""

import re
import subprocess
from pathlib import Path

GEO = Path("D:/GEO")
GL = GEO / "geolook"
FAIL, WARN, OK = [], [], []


def git(*a):
    return subprocess.run(["git", *a], cwd=GEO, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def rec(level, item, detail=""):
    {"F": FAIL, "W": WARN, "O": OK}[level].append((item, detail))


# ---------------------------------------------------------------- 1. 泄密面
print("=" * 74)
print("一、泄密面（最紧急：远程每 2 分钟被推一次）")
print("=" * 74)

r = git("remote", "-v")
print(f"\n远程:\n  {r.stdout.strip() or '（无）'}")

tracked = git("ls-files").stdout.splitlines()
print(f"\n被 git 跟踪的文件总数: {len(tracked)}")

SECRET_PATTERNS = [
    (r"(^|/)\.env$", ".env（引擎密钥）"),
    (r"(^|/)\.env\.", ".env.* 变体"),
    (r"(^|/)work/", "work/（项目数据、抓取快照、采样样本）"),
    (r"(^|/)\.jobs/", ".jobs/（任务日志）"),
    (r"(^|/)nile-xval/", "nile-xval/（我的临时脚本与 488KB 结果）"),
    (r"(^|/)plan/", "plan/（内部规划：竞品拆解与商业策略）"),
]
for pat, label in SECRET_PATTERNS:
    hits = [t for t in tracked if re.search(pat, t)]
    if hits:
        rec("F", f"已跟踪：{label}", f"{len(hits)} 个文件，例：{hits[0]}")
    else:
        rec("O", f"未跟踪：{label}")

gi = GEO / ".gitignore"
print(f"\n根 .gitignore: {'存在' if gi.exists() else '不存在'}")
if gi.exists():
    body = gi.read_text("utf-8", "ignore")
    print("  内容:")
    for line in body.strip().split("\n")[:20]:
        print(f"    {line}")
    for need in (".env", "work/", ".jobs/"):
        if need not in body:
            rec("F", f".gitignore 缺 {need}")
else:
    rec("F", "根目录没有 .gitignore")

# geolook 自己的 .gitignore 还在不在（它原本保护 work/ 和 .env）
gi2 = GL / ".gitignore"
if gi2.exists():
    rec("O", "geolook/.gitignore 仍在", gi2.read_text('utf-8','ignore').replace('\n','  '))
else:
    rec("F", "geolook/.gitignore 丢失", "原本用它保护 work/ 与 .env")

# ---------------------------------------------------------------- 2. 装得上跑得通
print("\n" + "=" * 74)
print("二、装得上 / 跑得通")
print("=" * 74)

for f, label in [("README.md", "英文 README"), ("README.zh-CN.md", "中文 README"),
                 ("README.ja.md", "日文 README"), ("LICENSE", "许可证"),
                 ("SKILL.md", "Claude skill"), (".env.example", ".env 模板")]:
    (rec("O", label) if (GL / f).exists() else rec("F", f"缺 {label}", f))

# CLI 入口是否都能响应
cmds = ["init", "new", "crawl", "audit", "sample", "plan", "generate",
        "report", "verify", "deliver", "deliverables", "ui", "publish", "status"]
bad = []
for c in cmds:
    p = subprocess.run(["py", "-3.12", "scripts/geo.py", c, "--help"],
                       cwd=GL, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        bad.append(c)
rec("F" if bad else "O", "CLI 子命令自检", f"失败: {bad}" if bad else f"{len(cmds)} 个全部响应")

# ---------------------------------------------------------------- 3. 文档一致性
print("\n" + "=" * 74)
print("三、文档与实现是否一致（RULES R8）")
print("=" * 74)

readmes = [GL / "README.md", GL / "README.zh-CN.md", GL / "README.ja.md"]
STALE = [
    ("you only pay your own engine API sampling costs", "英文 README 仍说用户自付 API 费"),
    ("只花你自己的引擎 API 采样费", "中文 README 仍说用户自付 API 费"),
    ("自分のエンジン API サンプリング費", "日文 README 仍说用户自付 API 费"),
    ("Windows via WSL", "仍说 Windows 需要 WSL"),
    ("platform-macOS%20%7C%20Linux-", "平台徽章仍未含 Windows"),
]
for f in readmes:
    if not f.exists():
        continue
    t = f.read_text("utf-8", "ignore")
    for needle, label in STALE:
        if needle in t:
            rec("F", label, f.name)

# 遗留标记
for p in sorted(GL.rglob("*.py")):
    if any(x in p.parts for x in (".git", "work", "__pycache__")):
        continue
    for i, line in enumerate(p.read_text("utf-8", "ignore").split("\n"), 1):
        if re.search(r"\b(FIXME|XXX|HACK)\b", line):
            rec("W", "代码遗留标记", f"{p.relative_to(GL)}:{i}")

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 74)
print(f"结果：阻塞 {len(FAIL)} · 待优化 {len(WARN)} · 通过 {len(OK)}")
print("=" * 74)
for label, items in (("阻塞交付", FAIL), ("建议优化", WARN)):
    if items:
        print(f"\n【{label}】")
        for item, detail in items:
            print(f"  · {item}" + (f"  —— {detail[:88]}" if detail else ""))
print("\n【已通过】")
for item, detail in OK:
    print(f"  · {item}" + (f"  —— {detail[:60]}" if detail else ""))
