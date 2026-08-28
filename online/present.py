"""把 geolook 项目数据收成客户能看懂的四页。

口径守执行文档第 8 节：点名题不计提及率、没有样本不是 0、竞品没被真实
答案出现过就不展示、位次叫出现顺序。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "geolook" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import analytics as A  # noqa: E402
import geolib as G  # noqa: E402
import sample as S  # noqa: E402
import voice as V  # noqa: E402


def _cfg(slug: str) -> dict:
    return G.load_config(slug)


def _analytics(slug: str) -> dict:
    try:
        return A.build(slug)
    except Exception:  # noqa: BLE001  呈现层坏了不能把整页打成 500
        return {"health": {"score": None, "subs": {}, "measured": []},
                "engines": [], "competitors": {"table": []}, "trend": [],
                "questions": [], "latest_date": None, "q_delta": []}


def _tasks(slug: str) -> list[dict]:
    td = G.read_json(G.project_dir(slug) / "tasks.json", {"tasks": []})
    return td.get("tasks") or []


def _customer_status(t: dict) -> str:
    st = t.get("status") or "todo"
    if st == "doing":
        return "doing"
    ev = t.get("evidence") or []
    last = ev[-1] if ev else {}
    # 曾经完成、重测未达标：回到待办并标退步
    if (t.get("regressed_at") or t.get("closed_at")) and last.get("result") == "fail":
        return "regressed"
    if st == "done":
        return "done"
    if st == "blocked":
        return "confirm"
    return "todo"


def customer_task(t: dict) -> dict | None:
    acc = t.get("acceptance") or {}
    done_when = (acc.get("desc") or "").strip()
    if not done_when:
        return None
    st = _customer_status(t)
    return {
        "id": t.get("id"),
        "band": V.band(t.get("priority") or "P1"),
        "priority": t.get("priority") or "P1",
        "do": V.humanize(t.get("action") or t.get("title") or ""),
        "why": V.humanize(t.get("why") or ""),
        "done_when": V.humanize(done_when),
        "status": st,
        "status_label": V.status_label(st),
        "auto": acc.get("type") == "auto",
        "confirm_needed": acc.get("type") == "manual" and st != "done",
        "affected": t.get("affected") or [],
    }


def action_plan(slug: str) -> list[dict]:
    order = {"先做": 0, "接着做": 1, "可以后做": 2}
    open_first = {"退步了": 0, "未开始": 1, "进行中": 2, "需人工确认": 3, "已完成": 4}
    items = [c for t in _tasks(slug) if (c := customer_task(t))]
    items.sort(key=lambda x: (open_first.get(x["status_label"], 9),
                              order.get(x["band"], 9), x["id"] or ""))
    return items


def next_three(slug: str) -> list[dict]:
    return [t for t in action_plan(slug) if t["status"] != "done"][:3]


def _has_samples(an: dict) -> bool:
    """有真实答案才算测过。只有体检/蓝图时不算，避免把覆盖率当成整体表现。"""
    return any((e.get("samples") or 0) > 0 for e in (an.get("engines") or []))


def _plugin_pending(slug: str, engines: list[dict]) -> dict:
    """无公开 API 的引擎：不挡第一份报告，总览一条提示去装插件。"""
    cfg = _cfg(slug)
    sampled = {e.get("platform") for e in engines if (e.get("samples") or 0) > 0}
    want = []
    for code in cfg.get("platforms") or []:
        if code in S.MANUAL_ONLY and code not in sampled:
            want.append({"code": code, "name": S.label_of(code)})
    return {"count": len(want), "engines": want}


def _conclusion(an: dict, detecting: bool, *, has_audit: bool = False) -> dict:
    if detecting:
        return {
            "kind": "detecting",
            "text": "正在检测",
            "detail": ("大约 10–20 分钟。国内接口引擎会自动跑完；"
                       "有几家只能在网页里采，到时会提醒你。"),
        }
    engines = an.get("engines") or []
    mentioned = [e for e in engines
                 if e.get("mention") is not None and e["mention"] > 0]
    if not _has_samples(an):
        if has_audit:
            return {
                "kind": "partial",
                "text": "网站检查已完成，但还没拿到有效的 AI 回答",
                "detail": "先保留网站行动建议；AI 提及率仍然是「还没测」，不会写成 0。",
            }
        return {
            "kind": "empty",
            "text": "还没测过 AI 认不认识你。点「开始检测」，我们用自己的引擎跑一轮。",
        }
    if not mentioned:
        return {"kind": "none", "text": "AI 还没有主动提到你"}
    n = len(mentioned)
    names = "、".join(e.get("label") or e.get("platform") for e in mentioned[:4])
    return {"kind": "some",
            "text": f"{n} 个引擎会提到你" + (f"（{names}）" if names else "")}


def _metric(value, *, cite_na=False):
    if cite_na:
        return {"state": "na", "label": "不适用", "value": None}
    if value is None:
        return {"state": "unmeasured", "label": "还没测", "value": None}
    return {"state": "ok", "label": V.pct_or_unmeasured(value), "value": value}


def _has_recheck(slug: str) -> bool:
    import verify as VER
    vdir = G.project_dir(slug) / "verify"
    files = sorted(vdir.glob("*.json"), key=VER.report_key) if vdir.exists() else []
    return len(files) >= 2


def journey(slug: str, *, sampled: bool, detecting: bool = False,
            job: dict | None = None) -> dict:
    """客户只认这一条主线；页面和按钮都从同一状态推导，避免各说各话。"""
    plan = action_plan(slug)
    open_items = [t for t in plan if t["status"] != "done"]
    action = (job or {}).get("action")
    if detecting:
        current = "verify" if action in ("verify", "recheck") else "detect"
    elif not sampled:
        current = "detect"
    elif open_items:
        current = "act"
    elif not _has_recheck(slug):
        current = "verify"
    else:
        current = "report"

    order = ["detect", "act", "verify", "report"]
    labels = {
        "detect": ("检测现状", "先确认 AI 有没有主动提到你"),
        "act": ("完成当前 3 条", "一次只处理影响最大的三件事"),
        "verify": ("重测验收", "达标打勾，退步重新进入计划"),
        "report": ("生成报告", "把本期结论和进展发给同事"),
    }
    primary = {
        "detect": {"label": "开始检测", "route": "overview", "action": "detect"},
        "act": {"label": "继续当前 3 条", "route": "plan", "action": "route"},
        "verify": {"label": "重测这些改动", "route": "effect", "action": "route"},
        "report": {"label": "查看本期报告", "route": "report", "action": "route"},
    }[current]
    cur = order.index(current)
    return {
        "current": current,
        "step": cur + 1,
        "total": len(order),
        "primary": primary,
        "steps": [
            {"id": key, "label": labels[key][0], "detail": labels[key][1],
             "state": "done" if i < cur else ("active" if i == cur else "pending")}
            for i, key in enumerate(order)
        ],
        "open_count": len(open_items),
        "focus": open_items[:3],
    }


def overview(slug: str, *, detecting: bool = False, job: dict | None = None) -> dict:
    cfg = _cfg(slug)
    an = _analytics(slug)
    health = an.get("health") or {}
    engines = an.get("engines") or []
    comps = ((an.get("competitors") or {}).get("table") or [])
    # 竞品必须先在真实答案里出现过（或客户手动确认）才展示
    comps = [c for c in comps if (c.get("presence") or 0) > 0 or c.get("confirmed")]
    trend = an.get("trend") or []
    site = (cfg.get("brand") or {}).get("site") or ""
    has_audit = (G.project_dir(slug) / "audit.json").exists()
    mention = (health.get("subs") or {}).get("mention")
    cite = (health.get("subs") or {}).get("cite")
    score = health.get("score")
    plan = action_plan(slug)
    next3 = next_three(slug)
    sampled = _has_samples(an)
    journey_out = journey(slug, sampled=sampled, detecting=detecting, job=job)
    # 插件提示只在已经出过第一份结果之后出现，空状态用总览那句人话即可
    plugin = (_plugin_pending(slug, engines)
              if sampled or detecting else {"count": 0, "engines": []})

    engine_rows = []
    if sampled:
        for e in engines:
            engine_rows.append({
                "platform": e.get("platform"),
                "name": e.get("label") or S.label_of(e.get("platform") or ""),
                "mention": _metric(e.get("mention")),
                "top3": ("有进前三" if (e.get("pos_median") and e["pos_median"] <= 3)
                         else ("还没进前三" if e.get("mention") else "还没测")),
                "cites_you": bool(e.get("cite_counts") and e["cite_counts"][0]),
                "excerpt": (e.get("example") or {}).get("excerpt") or "",
                "question": (e.get("example") or {}).get("question") or "",
            })

    # 没有样本时不把阵地覆盖率当成「整体表现」，也不画空引擎/空竞品
    if not sampled or score is None:
        health_out = {"state": "unmeasured", "label": "还没测", "value": None}
        mention_out = _metric(None)
        cite_out = _metric(None, cite_na=not bool(site))
        trend_out = []
        comps_out = []
    else:
        health_out = {"state": "ok", "label": str(score), "value": score}
        mention_out = _metric(mention)
        cite_out = _metric(cite, cite_na=not bool(site))
        trend_out = trend if len(trend) >= 2 else []
        comps_out = [{"name": c.get("name"), "presence": c.get("presence"),
                      "label": f"同样的问题，AI 更常提到 {c.get('name')}"}
                     for c in comps[:6]]

    return {
        "slug": slug,
        "brand": (cfg.get("brand") or {}).get("name") or slug,
        "site": site,
        "market": cfg.get("market", "cn"),
        "detecting": detecting,
        "sampled": sampled,
        "job": {"id": (job or {}).get("id"), "status": (job or {}).get("status"),
                "label": (job or {}).get("label"),
                "action": (job or {}).get("action")} if job else None,
        "journey": journey_out,
        "conclusion": _conclusion(an, detecting, has_audit=has_audit),
        "health": health_out,
        "mention": mention_out,
        "cite": cite_out,
        "trend": trend_out,
        "engines": engine_rows,
        "competitors": comps_out,
        "next3": next3,
        "plan_open": sum(1 for t in plan if t["status"] != "done"),
        "plugin": plugin if plugin["count"] else None,
        "has_audit": has_audit,
    }


def effect(slug: str) -> dict:
    """效果页只回答：上次让你改的，哪些真的好了。"""
    pdir = G.project_dir(slug)
    import verify as VER
    vdir = pdir / "verify"
    files = sorted(vdir.glob("*.json"), key=VER.report_key) if vdir.exists() else []
    # 生成待办时会顺手跑一次验收，那是基线，不是「改完重测」
    if len(files) < 2:
        return {"date": None, "items": [], "empty": True}
    latest = G.read_json(files[-1], {}) if files else {}
    results = []
    for r in latest.get("results") or []:
        t = customer_task({**r, "acceptance": next(
            (x.get("acceptance") for x in _tasks(slug) if x.get("id") == r.get("id")),
            {"desc": r.get("note") or "重测后判定", "type": "auto"})})
        if not t:
            continue
        verdict = r.get("verdict")
        if verdict == "通过":
            t["effect"] = "达标"
        elif verdict == "未达标" and r.get("was") == "done":
            t["effect"] = "退步了"
        elif verdict == "待人工":
            t["effect"] = "需人工确认"
        else:
            t["effect"] = "还没好"
        t["note"] = V.humanize(r.get("note") or "")
        results.append(t)
    return {
        "date": (latest.get("verified_at") or "")[:10] or None,
        "items": results,
        "empty": not results,
    }


def report(slug: str) -> dict:
    ov = overview(slug)
    plan = action_plan(slug)
    done = [t for t in plan if t["status"] == "done"]
    open_ = [t for t in plan if t["status"] != "done"]
    rival = (ov["competitors"][0]["name"] if ov["competitors"] else None)
    return {
        "brand": ov["brand"],
        "site": ov["site"],
        "conclusion": ov["conclusion"]["text"],
        "health": ov["health"],
        "mention": ov["mention"],
        "engines": [{"name": e["name"], "mention": e["mention"]["label"],
                     "top3": e["top3"]} for e in ov["engines"]],
        "competitor_line": (f"同样的问题，AI 现在更常推 {rival}。"
                            if rival else "还没有在真实答案里看到明确竞品。"),
        "done": [{"id": t["id"], "do": t["do"]} for t in done],
        "open": [{"id": t["id"], "do": t["do"], "band": t["band"]} for t in open_],
        "period": ov.get("job"),
    }


def settings(slug: str) -> dict:
    cfg = _cfg(slug)
    b = cfg.get("brand") or {}
    questions = cfg.get("questions") or []
    import generate as GEN
    facts = GEN.parse_facts(slug, "zh")
    definition = facts.get("definition") or ""
    return {
        "brand": {
            "name": b.get("name") or "",
            "site": b.get("site") or "",
            "industry": b.get("industry") or "",
            "target_users": b.get("target_users") or "",
            "aliases": b.get("aliases") or [],
            "definition": definition,
        },
        "questions": [{"id": q.get("id"), "text": q.get("text"),
                       "group": q.get("group")} for q in questions],
        "question_count": len(questions),
        "facts_missing": not bool(definition),
    }


def plugin_queue(slug: str) -> list[dict]:
    """插件拉的待采队列：只有没有公开 API 的引擎。"""
    cfg = _cfg(slug)
    qs = cfg.get("questions") or []
    out = []
    for code in cfg.get("platforms") or []:
        if code not in S.MANUAL_ONLY:
            continue
        mk = S.market_of(code)
        for q in qs:
            qmk = q.get("market") or cfg.get("market") or "cn"
            if qmk not in (mk, "both") and mk not in (qmk, "both"):
                continue
            out.append({
                "platform": code,
                "name": S.label_of(code),
                "question_id": q.get("id"),
                "question": q.get("text"),
            })
    return out


def collect_queue(slug: str, *, limit: int = 40, groups: list[str] | None = None,
                  intent: str = "") -> dict:
    """兼容现有采样插件的队列形状（/api/collect/queue/{slug}）。"""
    cfg = _cfg(slug)
    picked = [g for g in (groups or []) if g]
    if not picked and intent == "buyer":
        picked = sorted(S.BUYER_GROUPS)
    allq = cfg.get("questions") or []
    qs = [x for x in allq if not picked or x.get("group") in picked][:limit]
    counts: dict[str, int] = {}
    for x in allq:
        g2 = x.get("group") or "未分组"
        counts[g2] = counts.get(g2, 0) + 1
    group_rows = [{"name": g2, "count": c, "buyer": g2 in S.BUYER_GROUPS}
                  for g2, c in sorted(counts.items(), key=lambda kv: -kv[1])]
    plats = [{"code": c, "label": lb, "market": mk}
             for c, (lb, mk) in S.MANUAL_ONLY.items()]
    plats += [{"code": c, "label": s2["name"], "market": s2["market"]}
              for c, s2 in S.PROVIDERS.items() if not S.available(c)]
    return {
        "slug": slug,
        "brand": (cfg.get("brand") or {}).get("name") or slug,
        "questions": qs,
        "platforms": plats,
        "groups": group_rows,
        "selected": picked,
    }


def project_card(slug: str) -> dict:
    cfg = _cfg(slug) if (G.project_dir(slug) / "geo.json").exists() else {}
    b = cfg.get("brand") or {}
    return {"slug": slug, "name": b.get("name") or slug, "site": b.get("site") or ""}
