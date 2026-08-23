"""确认：代码内容是否完好、被删仓库的提交是否还能找回。"""

import subprocess
from pathlib import Path

GEO = Path("D:/GEO")
GL = GEO / "geolook"

print("=== 代码内容抽查 ===")
checks = [
    (GL / "scripts/generate.py", "def gen_skill_md", "品牌 SKILL.md 生成器"),
    (GL / "scripts/generate.py", '"skill"', "ASSETS 含 skill"),
    (GL / "scripts/mcp_server.py", "def list_projects", "MCP 工具层"),
    (GL / "scripts/mcp_proto.py", "def serve", "MCP 协议层"),
    (GL / "scripts/ui.html", "Ground<span", "侧栏 logo 已改名"),
    (GL / "scripts/ui.html", "const ULANG='en'", "英文单语"),
    (GL / "scripts/ui.html", "Start measuring AI visibility", "总览重排"),
    (GL / "scripts/dashboard.py", "def _port_taken", "端口守卫"),
    (GL / "scripts/geolib.py", "def _lock_acquire", "可移植文件锁"),
    (GL / "scripts/jobs.py", "def _alive", "Windows 探活修复"),
    (GL / "scripts/crawl.py", "UA_RATE_STATUS", "429 信号分流"),
    (GL / "README.md", "vs. agentic commerce backends", "定位章节新口径"),
]
ok = 0
for path, needle, label in checks:
    hit = path.exists() and needle in path.read_text("utf-8", "ignore")
    ok += hit
    print(f"  [{'OK ' if hit else 'MISS'}] {label}")
print(f"  -> {ok}/{len(checks)} 项完好")

print("\n=== 已删除的中日资产确认 ===")
for rel in ("README.zh-CN.md", "README.ja.md", "docs/screenshots-ja", "docs/demo.ja.gif"):
    print(f"  [{'仍在' if (GL / rel).exists() else '已删'}] {rel}")

print("\n=== geolook/.git 是否真的没了 ===")
print(f"  geolook/.git 存在: {(GL / '.git').exists()}")

print("\n=== D:/GEO 仓库里能否找到我那 9 个提交 ===")
targets = {
    "5a8ba74": "probe_ai_ua 修复",
    "d402ae2": "Windows 支持",
    "8c1a0f3": "限速三语文案",
    "cc22030": "端口守卫",
    "8c517de": "品牌 SKILL.md",
    "e322974": "MCP server",
    "cb5efc9": "SKILL.md/MCP 接入界面",
    "b031d4b": "定位章节",
}
for sha, label in targets.items():
    r = subprocess.run(["git", "cat-file", "-t", sha], cwd=GEO,
                       capture_output=True, text=True)
    found = r.returncode == 0 and r.stdout.strip() == "commit"
    print(f"  [{'找到' if found else '丢失'}] {sha}  {label}")

print("\n=== D:/GEO 仓库概况 ===")
for cmd, label in [
    (["git", "remote", "-v"], "远程"),
    (["git", "rev-list", "--count", "HEAD"], "提交总数"),
    (["git", "log", "-1", "--format=%H %s"], "HEAD"),
]:
    r = subprocess.run(cmd, cwd=GEO, capture_output=True, text=True)
    print(f"  {label}: {(r.stdout or r.stderr).strip() or '（空）'}")

r = subprocess.run(["git", "ls-tree", "--name-only", "HEAD"], cwd=GEO,
                   capture_output=True, text=True)
print(f"  HEAD 顶层: {r.stdout.split()}")
