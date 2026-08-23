"""把 grounded 暴露成 MCP 工具，让任意 MCP 客户端（Claude Desktop / Cursor /
Codex）能直接调用，而不必先学 CLI。

协议层在 mcp_proto.py，本模块只管工具定义与 grounded 接线——规范变动时换协议层
不用动这里。

安全边界（都是有意的，别顺手放宽）：
  * **发布类操作一律不暴露**。README 的设计原则是「每次发布都是显式点击」，
    让 agent 能触发对外发布会直接违背它。
  * 写操作只有重跑体检与生成资产两个，且都不联网；抓取（会请求第三方站点）
    也不暴露——由 agent 驱动的网络副作用风险太高，交给人在 CLI/看板里做。
  * 任何返回值都不含 `.env` 内容或引擎密钥。
  * slug 走 geolib.SLUG_OK 白名单，挡住路径穿越。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geolib as G  # noqa: E402
from mcp_proto import Tool, ToolError, serve  # noqa: E402

VERSION = "0.1.0"

SLUG_ARG = {"type": "object",
            "properties": {"slug": {"type": "string", "description": "项目标识（用 list_projects 查）"}},
            "required": ["slug"]}


def _pdir(slug: str) -> Path:
    """校验 slug 并返回项目目录。

    不能直接用 G.project_dir——它对非法 slug 走 die()/sys.exit，
    在长驻服务里会把进程带走。
    """
    if not isinstance(slug, str) or not G.SLUG_OK.match(slug or ""):
        raise ToolError(f"非法项目标识：{slug!r}")
    d = G.WORK / slug
    if not (d / "geo.json").exists():
        raise ToolError(f"项目 {slug} 不存在（用 list_projects 看有哪些）")
    return d


def _cfg(slug: str) -> dict:
    return json.loads((_pdir(slug) / "geo.json").read_text("utf-8"))


# ---------------------------------------------------------------- 只读工具


def list_projects() -> list[dict]:
    if not G.WORK.exists():
        return []
    out = []
    for d in sorted(G.WORK.iterdir()):
        if not (d / "geo.json").exists():
            continue
        cfg = G.read_json(d / "geo.json", {})
        audit = G.read_json(d / "audit.json", {})
        tasks = (G.read_json(d / "tasks.json", {}) or {}).get("tasks", [])
        out.append({
            "slug": d.name,
            "brand": (cfg.get("brand") or {}).get("name", ""),
            "site": (cfg.get("brand") or {}).get("site", ""),
            "market": cfg.get("market"),
            "avg_score": audit.get("avg_score"),
            "pages_audited": audit.get("page_count"),
            "questions": len(cfg.get("questions") or []),
            "tickets_open": sum(1 for t in tasks if t.get("status") != "done"),
        })
    return out


def get_site_audit(slug: str) -> dict:
    """站点体检结果：四层依赖链 + 站点级信号 + 逐页六维分数。"""
    a = G.read_json(_pdir(slug) / "audit.json", {})
    if not a:
        raise ToolError(f"{slug} 还没有体检数据，先跑 run_audit（需要已有抓取结果）")
    site = a.get("site") or {}
    return {
        "avg_score": a.get("avg_score"),
        "page_count": a.get("page_count"),
        "grade_distribution": a.get("grade_distribution"),
        # 四层是「先修哪个」的判据：上游失败时下游优化在引擎侧不可见
        "layers": a.get("layers"),
        "site_issues": a.get("site_issues"),
        "block_gap": a.get("block_gap"),
        "site_signals": {k: site.get(k) for k in (
            "has_robots", "has_sitemap", "has_llms_txt", "ai_bots_blocked",
            "ai_ua_blocked", "ai_ua_rate_limited", "pages_ok", "pages_crawled")},
        "pages": [{k: p.get(k) for k in (
            "url", "score", "grade", "word_count", "dimensions",
            "sections_quotable", "sections_total", "issue_codes")}
            for p in a.get("pages", [])],
    }


def get_brand_facts(slug: str) -> dict:
    """品牌事实库 + 品牌配置。所有内容生产的事实底座。"""
    import generate as GEN

    cfg = _cfg(slug)
    f = GEN.parse_facts(slug)
    return {
        "brand": cfg.get("brand"),
        "market": cfg.get("market"),
        "definition": f.get("definition"),
        "numbers": f.get("numbers"),
        "suitable": f.get("suitable"),
        "unsuitable": f.get("unsuitable"),
        "facts_md_exists": bool(f),
        "note": "标「待确认」的条目没有来源，不要当事实用——需人工补齐",
    }


def list_tickets(slug: str, status: str | None = None) -> dict:
    """工单：优先级说多重要，风险等级说动手时多小心，两者独立。"""
    t = G.read_json(_pdir(slug) / "tasks.json", {}) or {}
    tasks = t.get("tasks", [])
    if status:
        tasks = [x for x in tasks if x.get("status") == status]
    return {
        "summary": t.get("summary"),
        "tickets": [{k: x.get(k) for k in (
            "id", "priority", "risk", "package", "title", "why", "action",
            "owner", "effort", "window", "status", "acceptance", "affected")}
            for x in tasks],
    }


def get_question_bank(slug: str, intent: str | None = None) -> list[dict]:
    qs = _cfg(slug).get("questions") or []
    if intent:
        qs = [q for q in qs if q.get("intent") == intent]
    return qs


def get_method_reference(section: str | None = None) -> str:
    """评分方法论。六维每条阈值都有公开实证锚定，改建议前先读这个。

    section 按标题匹配，**任意层级**——六维里像「可抽取块」这种是 H3，
    只切 H2 会漏掉。命中后返回该标题到下一个同级或更高级标题之间的内容。
    """
    p = G.ROOT / "references" / "method.md"
    if not p.exists():
        raise ToolError("references/method.md 不存在")
    text = p.read_text("utf-8")
    if not section:
        return text

    lines = text.split("\n")
    heads = [(i, len(m.group(1)), line) for i, line in enumerate(lines)
             if (m := re.match(r"^(#{1,6})\s+", line))]
    key = section.lower()
    out: list[str] = []
    for n, (idx, level, line) in enumerate(heads):
        if key not in line.lower():
            continue
        end = len(lines)
        for later_idx, later_level, _ in heads[n + 1:]:
            if later_level <= level:
                end = later_idx
                break
        out.append("\n".join(lines[idx:end]).rstrip())
    if not out:
        titles = [h[2].lstrip("# ").strip() for h in heads]
        raise ToolError(f"没找到标题含「{section}」的小节。可选标题："
                        + "；".join(titles[:20]))
    return "\n\n".join(out)


# ---------------------------------------------------------------- 写操作工具


def run_audit(slug: str) -> dict:
    """按已有抓取结果重跑六维评分。不联网——抓取请在 CLI 或看板里做。"""
    _pdir(slug)
    if not (_pdir(slug) / "evidence" / "pages.jsonl").exists():
        raise ToolError(f"{slug} 还没有抓取结果，先在 CLI 跑 "
                        f"`python3 scripts/geo.py crawl --slug {slug}`")
    import audit

    a = audit.run(slug)
    return {"avg_score": a.get("avg_score"), "page_count": a.get("page_count"),
            "grade_distribution": a.get("grade_distribution")}


def generate_assets(slug: str, assets: str | None = None) -> dict:
    """生成部署资产（llms.txt / JSON-LD / 片段 / 大纲 / 归因包 / 品牌 SKILL.md）。

    只产文件，不发布——发布必须由人在看板里显式确认。
    """
    _pdir(slug)
    import generate as GEN

    which = None
    if assets:
        which = [x.strip() for x in assets.split(",") if x.strip()]
        bad = [w for w in which if w not in GEN.ASSETS]
        if bad:
            raise ToolError(f"未知资产类型 {bad}；可选：{', '.join(GEN.ASSETS)}")
    idx = GEN.run(slug, which=which)
    return {"generated": idx.get("assets"), "market": idx.get("market")}


TOOLS = [
    Tool("list_projects", "列出本机所有 GEO 项目及其体检分数、待办工单数。",
         {"type": "object", "properties": {}}, list_projects),
    Tool("get_site_audit",
         "取站点体检结果：四层依赖链（访问→定向→理解→可引用）、站点级信号、"
         "逐页六维分数与问题码。修复顺序要从失败的最上游层开始。",
         SLUG_ARG, get_site_audit),
    Tool("get_brand_facts",
         "取品牌事实库与品牌配置。写任何内容前先读它——标「待确认」的没有来源，不能当事实用。",
         SLUG_ARG, get_brand_facts),
    Tool("list_tickets",
         "列工单，含优先级、风险等级与验收标准。优先级说多重要，风险说动手时多小心。",
         {"type": "object",
          "properties": {"slug": {"type": "string"},
                         "status": {"type": "string",
                                    "description": "可选过滤：todo / doing / done"}},
          "required": ["slug"]}, list_tickets),
    Tool("get_question_bank",
         "取问题库（目标问题及其诊断类型）。",
         {"type": "object",
          "properties": {"slug": {"type": "string"},
                         "intent": {"type": "string",
                                    "description": "可选过滤：buyer / educate / probe"}},
          "required": ["slug"]}, get_question_bank),
    Tool("get_method_reference",
         "取 GEO 评分方法论（references/method.md）。六维阈值都有公开实证锚定，"
         "给优化建议前先读，别凭常识。可用 section 取单节。",
         {"type": "object",
          "properties": {"section": {"type": "string",
                                     "description": "可选：小节关键词，如「可抽取块」「对题性」"}}},
         get_method_reference),
    Tool("run_audit",
         "按已有抓取结果重跑六维评分。不联网；抓取请在 CLI 或看板里做。",
         SLUG_ARG, run_audit, writes=True),
    Tool("generate_assets",
         "生成部署资产：llms.txt / JSON-LD / 片段 / 大纲 / 归因包 / 品牌 SKILL.md。"
         "只产文件，不发布。",
         {"type": "object",
          "properties": {"slug": {"type": "string"},
                         "assets": {"type": "string",
                                    "description": "可选，逗号分隔；省略则全产"}},
          "required": ["slug"]}, generate_assets, writes=True),
]


def main():
    serve("grounded", VERSION, TOOLS)


if __name__ == "__main__":
    main()
