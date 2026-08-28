#!/usr/bin/env python3
"""客户自助网站。密钥只在 geolook/.env，这里不读进响应、不提供填写框。"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "geolook" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import account as ACC  # noqa: E402
import geolib as G  # noqa: E402
import jobs as J  # noqa: E402
import present as P  # noqa: E402
import sample as S  # noqa: E402

APP = HERE / "app.html"
PORT_DEFAULT = 8787


def is_loopback(host: str | None) -> bool:
    return (host or "") in ("127.0.0.1", "localhost", "::1")


class Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"


def _infer_slug(url: str, name: str, explicit: str | None = None) -> str:
    if explicit:
        return G.slugify(explicit)
    if url:
        from urllib.parse import urlparse as up
        host = up(url if url.startswith("http") else "https://" + url).netloc
        return G.slugify(host.removeprefix("www.").split(".")[0])
    return G.slugify(name)


def _detection_profile(user: dict, cfg: dict, body: dict) -> dict:
    """套餐只决定采样范围/重复次数；客户不接触具体模型。"""
    plan = user.get("plan") or "saver"
    platforms = [p for p in (cfg.get("platforms") or []) if p in S.PROVIDERS]
    if plan == "saver":
        platforms = [p for p in platforms if S.PROVIDERS[p].get("market") == "cn"]
    return {
        "--platforms": ",".join(platforms),
        "--repeat": 3 if plan == "deep" else 1,
        "--limit": body.get("limit"),
    }


def _save_definition(slug: str, brand: dict, definition: str) -> None:
    """只维护客户填写的一句话定义；已有事实卡的其它内容原样保留。"""
    definition = (definition or "").strip()
    if not definition:
        return
    p = G.project_dir(slug) / "content" / "facts.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        text = p.read_text("utf-8")
        block = f"## 一句话定义\n\n> {definition}\n"
        pattern = r"##\s*一句话定义.*?(?=\n##|\Z)"
        text = re.sub(pattern, block.rstrip(), text, count=1, flags=re.S) if re.search(
            pattern, text, re.S) else text.rstrip() + "\n\n" + block
    else:
        aliases = "、".join(brand.get("aliases") or []) or "无"
        text = (
            "## 实体\n"
            f"- 规范名：{brand.get('name') or slug}\n"
            f"- 别名/简称：{aliases}\n"
            f"- 官网：{brand.get('site') or '无'}\n\n"
            "## 一句话定义\n\n"
            f"> {definition}\n"
        )
    p.write_text(text.rstrip() + "\n", "utf-8")


def _shared_report_html(report: dict) -> bytes:
    engines = "".join(
        f"<tr><td>{escape(str(e.get('name') or ''))}</td>"
        f"<td>{escape(str(e.get('mention') or '还没测'))}</td>"
        f"<td>{escape(str(e.get('top3') or '还没测'))}</td></tr>"
        for e in report.get("engines") or [])
    engines = engines or "<tr><td colspan='3'>还没测</td></tr>"
    done = "".join(
        f"<li>✓ {escape(str(t.get('do') or ''))}</li>"
        for t in report.get("done") or []) or "<li>还没有完成项</li>"
    open_ = "".join(
        f"<li><b>{escape(str(t.get('band') or ''))}</b> "
        f"{escape(str(t.get('do') or ''))}</li>"
        for t in (report.get("open") or [])[:5]) or "<li>本期行动已完成</li>"
    brand = escape(str(report.get("brand") or "品牌"))
    conclusion = escape(str(report.get("conclusion") or "还没测"))
    health = escape(str((report.get("health") or {}).get("label") or "还没测"))
    mention = escape(str((report.get("mention") or {}).get("label") or "还没测"))
    competitor = escape(str(report.get("competitor_line") or ""))
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{brand} · AI 认知报告</title><style>
body{{margin:0;background:#f3f4f8;color:#181920;font:15px/1.65 "Segoe UI","PingFang SC",sans-serif}}
main{{width:min(920px,calc(100% - 32px));margin:36px auto;background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 18px 55px #17182718}}
header{{padding:36px;background:#171822;color:#fff}}header small{{color:#9d94ff}}h1{{margin:7px 0 8px}}header p{{color:#b8bac6}}
.body{{padding:30px}}.kpis{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.kpi{{padding:18px;background:#f6f6fa;border-radius:14px}}
.kpi span{{display:block;color:#747782;font-size:12px}}.kpi b{{font-size:28px}}h2{{font-size:17px;margin-top:28px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #ececf1;text-align:left}}th{{font-size:11px;color:#747782}}
li{{margin:8px 0}}@media(max-width:600px){{.kpis{{grid-template-columns:1fr}}.body{{padding:20px}}}}
@media print{{body{{background:#fff}}main{{width:100%;margin:0;box-shadow:none}}}}</style></head>
<body><main><header><small>GROUNDED · AI BRAND REPORT</small><h1>{brand} · AI 认知报告</h1><p>{conclusion}</p></header>
<div class="body"><div class="kpis"><div class="kpi"><span>整体表现</span><b>{health}</b></div>
<div class="kpi"><span>AI 会不会主动说到你</span><b>{mention}</b></div></div>
<h2>引擎表现</h2><table><thead><tr><th>引擎</th><th>主动提及</th><th>出现顺序</th></tr></thead><tbody>{engines}</tbody></table>
<h2>竞品观察</h2><p>{competitor}</p><h2>本月完成</h2><ul>{done}</ul><h2>下一步</h2><ul>{open_}</ul></div></main></body></html>""".encode("utf-8")


def _strip_secrets(obj):
    secrets = [os.environ.get(k) for k in ACC.KEY_ENV_NAMES if os.environ.get(k)]
    blob = json.dumps(obj, ensure_ascii=False)
    for s in secrets:
        if s and s in blob:
            blob = blob.replace(s, "[redacted]")
    return json.loads(blob)


def _job_progress(job: dict | None) -> dict | None:
    if not job:
        return None
    status = job.get("status") or "running"
    action = job.get("action")
    log, _ = J.tail(job.get("id"), 0) if job.get("id") else ("", 0)
    if action in ("detect", "recheck"):
        marks = [
            ("═══ 1/4", 12, "正在读取网站"),
            ("═══ 2/4", 38, "正在检查页面"),
            ("═══ 3/4", 62, "正在询问 AI 引擎"),
            ("═══ 4/4", 88, "正在生成当前 3 条行动"
             if action == "detect" else "正在对照行动完成标准"),
        ]
    elif action == "verify":
        marks = [
            ("=== 重抓站点 ===", 20, "正在读取改动后的页面"),
            ("=== 重跑体检 ===", 52, "正在对照完成标准"),
            ("验收：", 90, "正在整理验收结果"),
        ]
    else:
        marks = []
    percent, label = 5, "正在准备任务"
    for marker, value, text in marks:
        if marker in log:
            percent, label = value, text
    if status == "done":
        percent, label = 100, "已完成"
    elif status in ("failed", "interrupted", "stopped"):
        label = "没有完成，可以重新尝试"
    return {
        "status": status,
        "percent": percent,
        "label": label,
        "failed": status in ("failed", "interrupted", "stopped"),
    }


def _refund_if_job_fails(email: str, job_id: str) -> threading.Thread:
    """任务启动成功后异步结算；中途失败/中断时把预扣额度退回。"""
    def watch():
        while True:
            job = J.get(job_id)
            if not job:
                return
            status = job.get("status")
            if status != "running":
                if status in ("failed", "interrupted", "stopped"):
                    ACC.refund(email)
                return
            time.sleep(0.5)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


class Handler(BaseHTTPRequestHandler):
    server_version = "grounded-online/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        if raw:
            c = SimpleCookie()
            c.load(raw)
            if "sid" in c:
                return c["sid"].value
        return self.headers.get("X-Session") or None

    def _plugin_tok(self) -> str | None:
        q = parse_qs(urlparse(self.path).query)
        return self.headers.get("X-Plugin-Token") or (q.get("token") or [None])[0]

    def _json(self, code: int, obj, *, set_cookie: str | None = None,
              clear_cookie: bool = False):
        body = json.dumps(_strip_secrets(obj), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        extra = "; Secure" if os.environ.get("GROUNDED_ONLINE_HTTPS") else ""
        if set_cookie:
            self.send_header(
                "Set-Cookie",
                f"sid={set_cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=1209600{extra}")
        if clear_cookie:
            self.send_header("Set-Cookie", "sid=; Path=/; Max-Age=0")
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        body = APP.read_bytes() if APP.exists() else b"<p>missing app.html</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html_bytes(self, code: int, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _need_user(self):
        u = ACC.user_of(self._token())
        if not u:
            self._json(401, {"error": "请先登录"})
            return None
        return u

    def _need_slug(self, u) -> str | None:
        q = parse_qs(urlparse(self.path).query)
        slug = (q.get("slug") or [None])[0] or (u.get("projects") or [None])[0]
        if not slug:
            self._json(400, {"error": "还没有项目，先贴一个网址开始检测"})
            return None
        if not ACC.owns(u, slug):
            self._json(403, {"error": "这个项目不属于你"})
            return None
        return slug

    def _local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _plugin_ok(self, slug: str):
        """插件令牌、登录态，或本机 127.0.0.1（与顾问看板同口径）。"""
        pu = ACC.plugin_user(self._plugin_tok())
        if pu and ACC.owns(pu, slug):
            return pu
        user = ACC.user_of(self._token())
        if user and ACC.owns(user, slug):
            return user
        if self._local() and (G.project_dir(slug) / "geo.json").exists():
            return {"email": "local-plugin", "projects": [slug]}
        return None

    def _fail(self, e: BaseException):
        G.info(f"{self.command} {self.path} {type(e).__name__}: {e}")
        try:
            self._json(500, {"error": "出了点问题，请稍后重试"})
        except Exception:  # noqa: BLE001
            pass

    def do_GET(self):
        try:
            self._dispatch_get()
        except Exception as e:  # noqa: BLE001
            self._fail(e)

    def do_POST(self):
        try:
            self._dispatch_post()
        except Exception as e:  # noqa: BLE001
            self._fail(e)

    def _dispatch_get(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/", "/app", "/app.html"):
            return self._html()
        if path == "/shared-report":
            token = (parse_qs(urlparse(self.path).query).get("token") or [None])[0]
            rec = ACC.report_access(token)
            if not rec:
                return self._html_bytes(
                    404, "<h1>报告链接无效或已过期</h1>".encode("utf-8"))
            return self._html_bytes(200, _shared_report_html(P.report(rec["slug"])))
        if path == "/api/me":
            user = ACC.user_of(self._token())
            return self._json(200, {"user": ACC.public_user(user) if user else None})
        if path == "/api/projects":
            user = ACC.user_of(self._token())
            if user:
                return self._json(200, [P.project_card(s) for s in (user.get("projects") or [])])
            plugin_user = ACC.plugin_user(self._plugin_tok())
            if plugin_user:
                return self._json(
                    200, [P.project_card(s) for s in (plugin_user.get("projects") or [])])
            if self._local():
                slugs = []
                if G.WORK.exists():
                    slugs = [p.name for p in G.WORK.iterdir()
                             if (p / "geo.json").exists()]
                return self._json(200, [P.project_card(s) for s in slugs])
            return self._json(401, {"error": "请先登录"})
        if path.startswith("/api/collect/queue/"):
            slug = path.split("/")[-1]
            if not self._plugin_ok(slug):
                return self._json(401, {"error": "采集令牌无效或已过期"})
            q = parse_qs(urlparse(self.path).query)
            try:
                limit = max(1, min(200, int((q.get("limit") or ["40"])[0])))
            except ValueError:
                limit = 40
            groups = [g for g in ((q.get("groups") or [""])[0] or "").split(",") if g.strip()]
            intent = (q.get("intent") or [""])[0]
            return self._json(200, P.collect_queue(slug, limit=limit, groups=groups,
                                                   intent=intent))
        if path == "/api/overview":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            jid = J.running_for(slug)
            job = J.get(jid) if jid else None
            if not job:
                recent = J.recent(slug, limit=1)
                job = recent[0] if recent else None
            running = bool(job and job.get("status") == "running")
            ov = P.overview(slug, detecting=running, job=job)
            ov["job_progress"] = _job_progress(job)
            ov["user"] = ACC.public_user(user)
            ov["estimate"] = ACC.estimate(user)
            if ov.get("plugin"):
                ov["plugin"]["has_token"] = True
            return self._json(200, ov)
        if path == "/api/plan":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            return self._json(200, {"items": P.action_plan(slug),
                                    "brand": P.overview(slug)["brand"]})
        if path == "/api/effect":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            return self._json(200, P.effect(slug))
        if path == "/api/report":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            return self._json(200, P.report(slug))
        if path == "/api/settings":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            out = P.settings(slug)
            out["user"] = ACC.public_user(user)
            out["plugin_needed"] = bool((P.overview(slug).get("plugin") or {}).get("count"))
            return self._json(200, out)
        if path == "/api/job":
            user = self._need_user()
            if not user:
                return
            q = parse_qs(urlparse(self.path).query)
            jid = (q.get("id") or [None])[0]
            off = int((q.get("offset") or ["0"])[0] or 0)
            job = J.get(jid) if jid else None
            if not job:
                return self._json(404, {"error": "任务不存在"})
            if not ACC.owns(user, job.get("slug")):
                return self._json(403, {"error": "这个项目不属于你"})
            public_job = {k: v for k, v in job.items() if k not in ("cmd", "pid")}
            log, new_off = J.tail(jid, off)
            return self._json(200, {"job": public_job, "log": log, "offset": new_off})
        if path == "/api/plugin/queue":
            pu = ACC.plugin_user(self._plugin_tok())
            if not pu:
                return self._json(401, {"error": "采集令牌无效或已过期"})
            slug = (pu.get("projects") or [None])[0]
            if not slug:
                return self._json(400, {"error": "还没有项目"})
            return self._json(200, {"slug": slug, "queue": P.plugin_queue(slug)})
        return self._json(404, {"error": "没有这个页面"})

    def _dispatch_post(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        body = self._read_json()

        if path == "/api/login":
            r = ACC.login(body.get("email", ""), body.get("password", ""))
            if not r.get("ok"):
                return self._json(400, r)
            return self._json(200, {"ok": True,
                                    "user": ACC.public_user(ACC.user_of(r["token"]))},
                              set_cookie=r["token"])
        if path == "/api/register":
            r = ACC.register(body.get("email", ""), body.get("password", ""),
                             body.get("name", ""))
            if not r.get("ok"):
                return self._json(400, r)
            return self._json(200, {"ok": True,
                                    "user": ACC.public_user(ACC.user_of(r["token"]))},
                              set_cookie=r["token"])
        if path == "/api/logout":
            ACC.logout(self._token())
            return self._json(200, {"ok": True}, clear_cookie=True)

        if path == "/api/projects":
            user = self._need_user()
            if not user:
                return
            url = (body.get("url") or "").strip()
            name = (body.get("name") or "").strip()
            materials = (body.get("materials") or "").strip()
            no_site = bool(body.get("no_site")) or not url
            if no_site and not name:
                return self._json(400, {"error": "没有官网时，请写下品牌或商品名"})
            slug = _infer_slug(url, name, body.get("slug"))
            existing = G.project_dir(slug) / "geo.json"
            if existing.exists():
                if ACC.owns(user, slug):
                    return self._json(200, {"ok": True, "slug": slug, "existing": True})
                return self._json(400, {"error": "这个网站已经建过项目"})
            import geo as CLI

            class A:
                pass
            a = A()
            a.url = url
            a.name = name or None
            a.slug = slug
            a.market = body.get("market") or "both"
            a.max_pages = int(body.get("max_pages") or 60)
            a.force = False
            a.no_site = no_site
            a.materials = materials
            try:
                CLI.cmd_init(a)
            except SystemExit:
                return self._json(400, {"error": "建项目没有成功，请换个网站或品牌名"})
            slug = a.slug or slug
            ACC.attach_project(user["email"], slug)
            return self._json(200, {"ok": True, "slug": slug})

        if path == "/api/detect":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            est = ACC.estimate(user)
            if est["blocked"]:
                return self._json(402, {"error": "本月次数用完", "quota": est["quota"]})
            cfg = G.load_config(slug)
            profile = _detection_profile(user, cfg, body)
            selected = [p for p in profile["--platforms"].split(",") if p]
            if not any(S.available(p) for p in selected):
                return self._json(
                    503, {"error": "检测服务还在准备中，请联系管理员后再试"})
            paid = ACC.consume(user["email"])
            if not paid.get("ok"):
                return self._json(402, {"error": paid.get("error") or "本月次数用完",
                                        "quota": paid.get("quota")})
            try:
                job = J.start(slug, "detect", {
                    "--max-pages": body.get("max_pages") or 60,
                    **profile,
                })
            except RuntimeError:
                ACC.refund(user["email"])
                return self._json(409, {"error": "已经在检测中，请稍等"})
            except Exception:
                ACC.refund(user["email"])
                return self._json(500, {"error": "启动检测失败，请稍后重试"})
            _refund_if_job_fails(user["email"], job["id"])
            return self._json(200, {"ok": True, "job": job,
                                    "quota": paid.get("quota"),
                                    "estimate": est["text"]})

        if path.startswith("/api/plan/") and path.endswith("/status"):
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            tid = path.split("/")[3]
            st = body.get("status")
            if st not in ("todo", "doing", "done"):
                return self._json(400, {"error": "状态不对"})
            import tasks as T
            try:
                T.set_status(slug, tid, st)
            except KeyError:
                return self._json(404, {"error": "找不到这条待办"})
            return self._json(200, {"ok": True})

        if path == "/api/effect/recheck":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            est = ACC.estimate(user)
            if est["blocked"]:
                return self._json(402, {"error": "本月次数用完", "quota": est["quota"]})
            cfg = G.load_config(slug)
            profile = _detection_profile(user, cfg, body)
            selected = [p for p in profile["--platforms"].split(",") if p]
            if not any(S.available(p) for p in selected):
                return self._json(
                    503, {"error": "检测服务还在准备中，请联系管理员后再试"})
            paid = ACC.consume(user["email"])
            if not paid.get("ok"):
                return self._json(402, {"error": paid.get("error") or "本月次数用完",
                                        "quota": paid.get("quota")})
            try:
                job = J.start(slug, "recheck", {"--max-pages": 60, **profile})
            except RuntimeError:
                ACC.refund(user["email"])
                return self._json(409, {"error": "已经在检测中，请稍等"})
            except Exception:
                ACC.refund(user["email"])
                return self._json(500, {"error": "启动重测失败，请稍后重试"})
            _refund_if_job_fails(user["email"], job["id"])
            return self._json(200, {"ok": True, "job": job})

        if path == "/api/settings/brand":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            with G.project_lock(slug):
                cfg = G.load_config(slug)
                b = cfg.setdefault("brand", {})
                for k in ("name", "industry", "target_users", "site"):
                    if k in body and body[k] is not None:
                        b[k] = str(body[k]).strip()
                if "aliases" in body:
                    raw = body["aliases"]
                    if isinstance(raw, str):
                        raw = raw.replace("，", ",").split(",")
                    b["aliases"] = [str(x).strip() for x in raw if str(x).strip()]
                G.write_json(G.project_dir(slug) / "geo.json", cfg)
                _save_definition(slug, b, str(body.get("definition") or ""))
            return self._json(200, {"ok": True, "brand": b})

        if path == "/api/plugin/token":
            user = self._need_user()
            if not user:
                return
            tok = ACC.plugin_token(user["email"])
            return self._json(
                200, {"ok": True, "token": tok, "expires_in_hours": 8})

        if path == "/api/report/share":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            tok = ACC.report_token(user["email"], slug)
            if not tok:
                return self._json(403, {"error": "无法分享这个项目的报告"})
            return self._json(
                200, {"ok": True, "url": f"/shared-report?token={tok}",
                      "expires_in_days": 7})

        if path.startswith("/api/collect/") and not path.startswith("/api/collect/queue"):
            slug = path.split("/")[-1]
            if not self._plugin_ok(slug):
                return self._json(401, {"error": "采集令牌无效或已过期"})
            records = body.get("records")
            if not isinstance(records, list) or not records:
                return self._json(400, {"error": "没有可回传的答案"})
            if len(records) > 200:
                return self._json(400, {"error": "一次最多回传 200 条"})
            jid = J.running_for(slug)
            job = J.get(jid) if jid else None
            if job and job.get("action") in ("sample", "detect", "recheck", "verify", "serve"):
                return self._json(409, {"error": "正在检测，等它结束再回传网页里采的答案"})
            with G.project_lock(slug):
                r = S.collect_import(slug, records)
            if not r.get("ok"):
                return self._json(400, {"error": r.get("error") or "回传没有成功"})
            return self._json(200, r)

        if path == "/api/plugin/sample":
            pu = ACC.plugin_user(self._plugin_tok() or body.get("token"))
            if not pu:
                return self._json(401, {"error": "采集令牌无效或已过期"})
            slug = (pu.get("projects") or [None])[0]
            if not slug:
                return self._json(400, {"error": "还没有项目"})
            jid = J.running_for(slug)
            job = J.get(jid) if jid else None
            if job and job.get("action") in ("sample", "detect", "recheck", "verify", "serve"):
                return self._json(409, {"error": "正在检测，等它结束再回传网页里采的答案"})
            with G.project_lock(slug):
                r = S.collect_import(slug, [body])
            if not r.get("ok"):
                return self._json(400, {"error": r.get("error") or "回传没有成功"})
            return self._json(200, r)
        return self._json(404, {"error": "没有这个接口"})


def _port_taken(host: str, port: int) -> bool:
    probe = "127.0.0.1" if host == "0.0.0.0" else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((probe, port)) == 0


def run(port: int = PORT_DEFAULT, host: str | None = None, open_browser: bool = True):
    G.load_env()
    host = host or os.environ.get("GROUNDED_ONLINE_HOST") or "127.0.0.1"
    ACC.ensure_demo(host)
    J.reap_orphans()
    if _port_taken(host, port):
        G.die(f"端口 {port} 已被占用。换一个：py online/server.py --port {port + 1}")
    httpd = Server((host, port), Handler)
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}/"
    G.info(f"客户网站已启动：{url}")
    if ACC.demo_allowed(host):
        G.info("演示账号 demo@wagnab.com / wagnab（项目 wagnab.com）")
    elif not is_loopback(host):
        G.info("非本机绑定：未创建演示账号。客户用自己注册的邮箱登录。")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        G.info("已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT_DEFAULT)
    ap.add_argument("--host", default=None)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    run(port=args.port, host=args.host, open_browser=not args.no_open)


