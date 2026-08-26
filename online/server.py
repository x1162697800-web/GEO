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


def _strip_secrets(obj):
    secrets = [os.environ.get(k) for k in ACC.KEY_ENV_NAMES if os.environ.get(k)]
    blob = json.dumps(obj, ensure_ascii=False)
    for s in secrets:
        if s and s in blob:
            blob = blob.replace(s, "[redacted]")
    return json.loads(blob)


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
        if set_cookie:
            self.send_header(
                "Set-Cookie",
                f"sid={set_cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=1209600")
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

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/", "/app", "/app.html"):
            return self._html()
        if path == "/api/me":
            user = ACC.user_of(self._token())
            return self._json(200, {"user": ACC.public_user(user) if user else None})
        if path == "/api/overview":
            user = self._need_user()
            if not user:
                return
            slug = self._need_slug(user)
            if not slug:
                return
            jid = J.running_for(slug)
            job = J.get(jid) if jid else None
            ov = P.overview(slug, detecting=bool(job), job=job)
            ov["user"] = ACC.public_user(user)
            ov["estimate"] = ACC.estimate(user)
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
            out["plugin_token"] = ACC.plugin_token(user["email"])
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
            log, new_off = J.tail(jid, off)
            return self._json(200, {"job": job, "log": log, "offset": new_off})
        if path == "/api/plugin/queue":
            pu = ACC.plugin_user(self._plugin_tok())
            if not pu:
                return self._json(401, {"error": "采集令牌无效或已过期"})
            slug = (pu.get("projects") or [None])[0]
            if not slug:
                return self._json(400, {"error": "还没有项目"})
            return self._json(200, {"slug": slug, "queue": P.plugin_queue(slug)})
        return self._json(404, {"error": "没有这个页面"})

