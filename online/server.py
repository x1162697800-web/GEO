#!/usr/bin/env python3
"""客户自助网站。密钥只在 geolook/.env，这里不读进响应、不提供填写框。"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import webbrowser
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
    if action == "detect":
        marks = [
            ("═══ 1/4", 12, "正在读取网站"),
            ("═══ 2/4", 38, "正在检查页面"),
            ("═══ 3/4", 62, "正在询问 AI 引擎"),
            ("═══ 4/4", 88, "正在生成当前 3 条行动"),
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
            a.market = body.get("market") or ("global" if no_site else "both")
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
            if not any(S.available(p) for p in S.PROVIDERS):
                return self._json(
                    503, {"error": "检测服务还在准备中，请联系管理员后再试"})
            paid = ACC.consume(user["email"])
            if not paid.get("ok"):
                return self._json(402, {"error": paid.get("error") or "本月次数用完",
                                        "quota": paid.get("quota")})
            try:
                job = J.start(slug, "detect", {
                    "--max-pages": body.get("max_pages") or 60,
                    "--limit": body.get("limit"),
                })
            except RuntimeError:
                ACC.refund(user["email"])
                return self._json(409, {"error": "已经在检测中，请稍等"})
            except Exception:
                ACC.refund(user["email"])
                return self._json(500, {"error": "启动检测失败，请稍后重试"})
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
            try:
                job = J.start(slug, "verify", {})
            except RuntimeError:
                return self._json(409, {"error": "已经在检测中，请稍等"})
            return self._json(200, {"ok": True, "job": job})

        if path == "/api/settings/brand":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
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
            return self._json(200, {"ok": True, "brand": b})

        if path == "/api/plugin/token":
            user = self._need_user()
            if not user:
                return
            tok = ACC.plugin_token(user["email"])
            return self._json(
                200, {"ok": True, "token": tok, "expires_in_hours": 8})

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
            if job and job.get("action") in ("sample", "detect", "serve"):
                return self._json(409, {"error": "正在检测，等它结束再回传网页里采的答案"})
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


