"""客户文案：内部术语换成执行文档第 9 节的人话。

判据层继续用 P0 / SPA / 实体消歧；呈现层只许出现对照表里的说法。
替换按长词优先，避免把 URL 或代码路径里的片段误伤成句子。
"""
from __future__ import annotations

import re

PRIORITY = {"P0": "先做", "P1": "接着做", "P2": "可以后做"}
STATUS = {
    "todo": "未开始",
    "doing": "进行中",
    "done": "已完成",
    "confirm": "需人工确认",
    "regressed": "退步了",
}

# 长的先换。括号里的内部词也要清掉，否则「（SSR / 预渲染）」会漏网。
_PHRASES = [
    ("实体消歧的地基", "先让人分清我们是谁"),
    ("实体消歧地基", "先让人分清我们是谁"),
    ("实体消歧", "先统一「我们是谁」这一句话"),
    ("对受影响路由启用 SSR 或预渲染", "让这些页面打开后就能读到正文"),
    ("启用 SSR 或预渲染", "改成打开网页就能读到正文"),
    ("SSR / 预渲染", "打开网页就能读到正文"),
    ("SSR 或预渲染", "打开网页就能读到正文"),
    ("确保 curl 拿到的 HTML 含完整正文", "确保不打开浏览器也能读到完整正文"),
    ("纯前端渲染", "网页打开后，搜索和 AI 读不到正文"),
    ("前端渲染空壳页", "打开后读不到正文的页面"),
    ("静态 HTML 无正文", "网页打开后，搜索和 AI 读不到正文"),
    ("可抽取块", "定义、数字、对比这些硬信息"),
    ("无提示提及率", "AI 会不会主动说到你"),
    ("引用官网率", "答案有没有指向你的来源"),
    ("引用份额", "答案有没有指向你的来源"),
    ("GEO 健康分", "整体表现"),
    ("健康分", "整体表现"),
    ("JSON-LD", "给搜索和 AI 看的页面说明"),
    ("页面说明 description", "页面说明"),
    ("重跑 audit 均分", "重测后网站整体分数"),
    ("用 `geo.py generate --asset attribution` 产出配置包", "按我们给的说明建好来源追踪"),
    ("llms.txt", "给 AI 看的官方说明页"),
    ("content/facts.en.md", "「我们是谁」这份说明"),
    ("content/facts.md", "「我们是谁」这份说明"),
    ("facts.md", "「我们是谁」这份说明"),
    ("brand_rank", "出现顺序"),
    ("X-Robots-Tag", "网站返回的抓取指令"),
    ("noindex", "不让搜索抓取"),
]


def humanize(text: str | None) -> str:
    if not text:
        return ""
    out = text
    for src, dst in _PHRASES:
        out = out.replace(src, dst)
    out = re.sub(r"\bSSR\b", "打开网页就能读到正文", out)
    out = re.sub(r"\bSPA\b", "网页打开后，搜索和 AI 读不到正文", out)
    out = re.sub(r"\bP0\b", "先做", out)
    out = re.sub(r"\bP1\b", "接着做", out)
    out = re.sub(r"\bP2\b", "可以后做", out)
    # 顾问文档引用客户看不懂，整段括号拿掉
    out = re.sub(r"[（(][^）)]*\.md[^）)]*[）)]", "", out)
    out = re.sub(r"`geo\.py[^`]*`", "导出的说明", out)
    out = re.sub(r"[\w./-]+\.md", "", out)
    out = re.sub(r"参照\s*[，,]?\s*", "", out)
    out = re.sub(r"\baudit\.json\b", "体检结果", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def band(priority: str) -> str:
    return PRIORITY.get(priority, "接着做")


def status_label(key: str) -> str:
    return STATUS.get(key, "未开始")


def pct_or_unmeasured(value, *, as_percent=True) -> str | None:
    """没有样本时返回 None（呈现层写成「还没测」），绝不退化成 0。"""
    if value is None:
        return None
    if as_percent:
        return f"{round(value * 100)}%"
    return str(value)
