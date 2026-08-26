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
import copy as C  # noqa: E402


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
    if st == "done":
        return "done"
    if st == "doing":
        return "doing"
    if st == "blocked":
        return "confirm"
    ev = t.get("evidence") or []
    last = ev[-1] if ev else {}
    # 曾经完成、重测未达标：回到待办并标退步
    if t.get("closed_at") and last.get("result") == "fail":
        return "regressed"
    return "todo"


def customer_task(t: dict) -> dict | None:
    acc = t.get("acceptance") or {}
    done_when = (acc.get("desc") or "").strip()
    if not done_when:
        return None
    st = _customer_status(t)
    return {
        "id": t.get("id"),
        "band": C.band(t.get("priority") or "P1"),
        "priority": t.get("priority") or "P1",
        "do": C.humanize(t.get("action") or t.get("title") or ""),
        "why": C.humanize(t.get("why") or ""),
        "done_when": C.humanize(done_when),
        "status": st,
        "status_label": C.status_label(st),
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


def _plugin_pending(slug: str, engines: list[dict]) -> dict:
    """无公开 API 的引擎：不挡第一份报告，总览一条提示去装插件。"""
    cfg = _cfg(slug)
    sampled = {e.get("platform") for e in engines}
    want = []
    for code in cfg.get("platforms") or []:
        if code in S.MANUAL_ONLY and code not in sampled:
            want.append({"code": code, "name": S.label_of(code)})
    return {"count": len(want), "engines": want}


def _conclusion(an: dict, detecting: bool) -> dict:
    if detecting:
        return {
            "kind": "detecting",
            "text": ("正在用我们的引擎检测，大约 10–20 分钟。"
                     "国内接口引擎会自动跑完；有几家只能在网页里采，到时会提醒你。"),
        }
    health = (an.get("health") or {}).get("score")
    engines = an.get("engines") or []
    mentioned = [e for e in engines
                 if e.get("mention") is not None and e["mention"] > 0]
    sampled = any(e.get("samples") for e in engines) or bool(an.get("latest_date"))
    if not sampled:
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
    return {"state": "ok", "label": C.pct_or_unmeasured(value), "value": value}


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
    mention = (health.get("subs") or {}).get("mention")
    cite = (health.get("subs") or {}).get("cite")
    score = health.get("score")
    plan = action_plan(slug)
    next3 = next_three(slug)
    plugin = _plugin_pending(slug, engines)

    engine_rows = []
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

    return {
        "slug": slug,
        "brand": (cfg.get("brand") or {}).get("name") or slug,
        "site": site,
        "market": cfg.get("market", "cn"),
        "detecting": detecting,
        "job": {"id": (job or {}).get("id"), "status": (job or {}).get("status"),
                "label": (job or {}).get("label")} if job else None,
        "conclusion": _conclusion(an, detecting),
        "health": _metric(None if score is None else score / 100) if score is None
                  else {"state": "ok", "label": str(score), "value": score},
        "mention": _metric(mention),
        "cite": _metric(cite, cite_na=not bool(site)),
        "trend": trend if len(trend) >= 2 else [],
        "engines": engine_rows,
        "competitors": [{"name": c.get("name"), "presence": c.get("presence"),
                         "label": f"同样的问题，AI 更常提到 {c.get('name')}"}
                        for c in comps[:6]],
        "next3": next3,
        "plan_open": sum(1 for t in plan if t["status"] != "done"),
        "plugin": plugin if plugin["count"] else None,
        "has_audit": (G.project_dir(slug) / "audit.json").exists(),
    }


def effect(slug: str) -> dict:
    """效果页只回答：上次让你改的，哪些真的好了。"""
    pdir = G.project_dir(slug)
    import verify as V
    vdir = pdir / "verify"
    files = sorted(vdir.glob("*.json"), key=V.report_key) if vdir.exists() else []
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
        t["note"] = C.humanize(r.get("note") or "")
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
    return {
        "brand": {
            "name": b.get("name") or "",
            "site": b.get("site") or "",
            "industry": b.get("industry") or "",
            "target_users": b.get("target_users") or "",
            "aliases": b.get("aliases") or [],
        },
        "questions": [{"id": q.get("id"), "text": q.get("text"),
                       "group": q.get("group")} for q in questions],
        "question_count": len(questions),
        "facts_missing": not (G.project_dir(slug) / "content" / "facts.md").exists()
                         and not (G.project_dir(slug) / "content" / "facts.en.md").exists(),
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
