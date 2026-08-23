"""统计英文化的真实工作量：区分「界面模板里的中文」和「后端生成的中文」。

后者是关键——它们不经过 i18n 层，删掉翻译机制也不会变成英文。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "geolook"
CJK = re.compile(r"[\u4e00-\u9fff]")

# 用户可见的中文（会流进界面或产物），排除注释和文档
TARGETS = {
    "scripts/ui.html": "界面模板 + i18n 字典",
    "scripts/audit.py": "体检问题描述 → 界面",
    "scripts/tasks.py": "工单标题/理由/动作 → 界面",
    "scripts/crawl.py": "抓取提示 → 日志",
    "scripts/generate.py": "资产内容 → 产物文件",
    "scripts/bootstrap.py": "推导提示",
    "scripts/report.py": "报告正文 → 交付物",
    "scripts/deliverables.py": "交付物正文",
    "scripts/analytics.py": "指标标签 → 界面",
    "scripts/sample.py": "采样提示",
    "scripts/geo.py": "CLI 帮助与提示",
    "scripts/dashboard.py": "API 错误信息",
    "scripts/mcp_server.py": "MCP 工具描述",
    "scripts/verify.py": "验收判词 → 界面",
    "scripts/deliver.py": "交付包文案",
    "scripts/blueprint.py": "蓝图文案",
    "scripts/expand.py": "拓词文案",
    "scripts/jobs.py": "任务标签 → 界面",
    "extension/sidepanel.js": "插件界面",
    "extension/sidepanel.html": "插件界面",
    "extension/content.js": "插件提示",
}


def scan(path: Path):
    """返回 (含中文的代码行数, 注释行数, 字符串字面量里的中文行数)。"""
    if not path.exists():
        return None
    code = comment = 0
    for line in path.read_text("utf-8").split("\n"):
        if not CJK.search(line):
            continue
        s = line.strip()
        if s.startswith("#") or s.startswith("//") or s.startswith("*"):
            comment += 1
        else:
            code += 1
    return code, comment


print(f"{'文件':<26} {'代码行':>7} {'注释行':>7}  作用")
print("-" * 92)
tot_code = tot_comment = 0
for rel, note in TARGETS.items():
    r = scan(ROOT / rel)
    if not r:
        continue
    code, comment = r
    tot_code += code
    tot_comment += comment
    print(f"{rel:<26} {code:>7} {comment:>7}  {note}")
print("-" * 92)
print(f"{'合计':<26} {tot_code:>7} {tot_comment:>7}")

# ui.html 里 i18n 机制本身占多少
ui = (ROOT / "scripts" / "ui.html").read_text("utf-8").split("\n")
i18n = [i for i, l in enumerate(ui, 1)
        if re.search(r"UI_D|UI_SUB|UI_RX|ULANG|setLang|uiTranslate", l)]
print(f"\nui.html 共 {len(ui)} 行；i18n 机制相关 {len(i18n)} 行"
      f"（{i18n[0]}–{i18n[-1]} 区间内）")

# 英文字典能覆盖多少现有中文串
txt = (ROOT / "scripts" / "ui.html").read_text("utf-8")
en_keys = set(re.findall(r"'([^']*[\u4e00-\u9fff][^']*)':'", txt))
print(f"UI_D 里已有译文的中文键：约 {len(en_keys)} 条（英文化时可直接取用）")
