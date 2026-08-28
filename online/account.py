"""账号、会话、额度。密钥不进这里，也不进任何客户接口。

三档只决定每月能跑几次检测，客户不选模型。超限返回人话，不报 API 错误。
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from functools import wraps
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
ACCOUNTS = DATA / "accounts.json"
_LOCK = threading.RLock()

# 省钱：注册免费 1 次；标准：付费默认每月 2 次；加密：加购（第一期只记账）
PLANS = {
    "saver": {"label": "省钱", "monthly": 1, "blurb": "先看国内 AI 认不认识你"},
    "standard": {"label": "标准", "monthly": 2, "blurb": "国内 + 海外，够写月报"},
    "deep": {"label": "加密", "monthly": 8, "blurb": "同一题多问几次，看稳不稳"},
}


def _locked(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapped


def _now_month() -> str:
    return time.strftime("%Y-%m")


def _load() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    if not ACCOUNTS.exists():
        return {"users": {}, "sessions": {}, "plugin": {}}
    try:
        return json.loads(ACCOUNTS.read_text("utf-8"))
    except json.JSONDecodeError:
        return {"users": {}, "sessions": {}, "plugin": {}}


def _save(db: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = ACCOUNTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(ACCOUNTS)


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


def demo_allowed(host: str | None = None) -> bool:
    """演示账号只给本机交付验收。公网或显式关掉时不种已知密码。"""
    flag = (os.environ.get("GROUNDED_DEMO") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if host and host not in ("127.0.0.1", "localhost", "::1"):
        return False
    return True


@_locked
def ensure_demo(host: str | None = None) -> None:
    """本地演示账号绑到已有的 wagnab 项目，方便按执行文档走主路径。"""
    if not demo_allowed(host):
        return
    db = _load()
    if "demo@wagnab.com" in db["users"]:
        return
    salt = secrets.token_hex(8)
    db["users"]["demo@wagnab.com"] = {
        "email": "demo@wagnab.com",
        "name": "WagNab 演示",
        "salt": salt,
        "password": _hash("wagnab", salt),
        "plan": "standard",
        "created": time.strftime("%Y-%m-%d"),
        "projects": ["wagnab"],
        "quota": {"month": _now_month(), "used": 0},
        "frozen": False,
    }
    _save(db)


@_locked
def register(email: str, password: str, name: str = "") -> dict:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "error": "请填写有效邮箱"}
    if len(password or "") < 6:
        return {"ok": False, "error": "密码至少 6 位"}
    db = _load()
    if email in db["users"]:
        return {"ok": False, "error": "这个邮箱已经注册过"}
    salt = secrets.token_hex(8)
    db["users"][email] = {
        "email": email, "name": name or email.split("@")[0],
        "salt": salt, "password": _hash(password, salt),
        "plan": "saver", "created": time.strftime("%Y-%m-%d"),
        "projects": [],
        "quota": {"month": _now_month(), "used": 0},
        "frozen": False,
    }
    _save(db)
    return {"ok": True, "token": _session(email)}


@_locked
def login(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    db = _load()
    u = db["users"].get(email)
    if not u or u["password"] != _hash(password, u["salt"]):
        return {"ok": False, "error": "邮箱或密码不对"}
    if u.get("frozen"):
        return {"ok": False, "error": "这个账号暂时被冻结，请联系我们"}
    return {"ok": True, "token": _session(email)}


@_locked
def _session(email: str) -> str:
    db = _load()
    token = secrets.token_urlsafe(24)
    db.setdefault("sessions", {})[token] = {"email": email, "at": time.time()}
    cutoff = time.time() - 86400 * 14
    db["sessions"] = {k: v for k, v in db["sessions"].items() if v.get("at", 0) > cutoff}
    _save(db)
    return token


@_locked
def user_of(token: str | None) -> dict | None:
    if not token:
        return None
    db = _load()
    s = (db.get("sessions") or {}).get(token)
    if not s:
        return None
    return (db.get("users") or {}).get(s["email"])


@_locked
def logout(token: str | None) -> None:
    if not token:
        return
    db = _load()
    (db.get("sessions") or {}).pop(token, None)
    _save(db)


def public_user(u: dict) -> dict:
    q = _quota(u)
    plan = PLANS.get(u.get("plan") or "saver", PLANS["saver"])
    return {
        "email": u["email"],
        "name": u.get("name") or "",
        "plan": u.get("plan") or "saver",
        "plan_label": plan["label"],
        "plan_blurb": plan["blurb"],
        "projects": list(u.get("projects") or []),
        "quota": q,
    }


def _quota(u: dict) -> dict:
    plan = PLANS.get(u.get("plan") or "saver", PLANS["saver"])
    q = u.get("quota") or {}
    month = _now_month()
    used = q.get("used", 0) if q.get("month") == month else 0
    cap = plan["monthly"]
    left = max(0, cap - used)
    return {"month": month, "used": used, "cap": cap, "left": left,
            "label": f"本月还剩 {left} 次{plan['label']}检测"}


@_locked
def attach_project(email: str, slug: str) -> None:
    db = _load()
    u = db["users"].get(email)
    if not u:
        return
    if slug not in u["projects"]:
        u["projects"].append(slug)
    _save(db)


def owns(u: dict, slug: str) -> bool:
    return slug in (u.get("projects") or [])


def estimate(u: dict) -> dict:
    q = _quota(u)
    return {
        "ok": q["left"] > 0,
        "text": "本次大约消耗 1 次标准检测" if (u.get("plan") != "saver")
                else "本次大约消耗 1 次免费检测",
        "quota": q,
        "blocked": q["left"] <= 0,
        "block_reason": "本月次数用完" if q["left"] <= 0 else None,
    }


@_locked
def consume(email: str) -> dict:
    """跑检测前扣一次。超限不扣，返回人话。"""
    db = _load()
    u = db["users"].get(email)
    if not u:
        return {"ok": False, "error": "请先登录"}
    if u.get("frozen"):
        return {"ok": False, "error": "这个账号暂时被冻结，请联系我们"}
    q = _quota(u)
    if q["left"] <= 0:
        return {"ok": False, "error": "本月次数用完", "quota": q}
    u["quota"] = {"month": q["month"], "used": q["used"] + 1}
    _save(db)
    return {"ok": True, "quota": _quota(u)}


@_locked
def refund(email: str) -> dict:
    """启动检测失败时把刚扣的一次加回去。"""
    db = _load()
    u = db["users"].get(email)
    if not u:
        return {"ok": False}
    q = _quota(u)
    u["quota"] = {"month": q["month"], "used": max(0, q["used"] - 1)}
    _save(db)
    return {"ok": True, "quota": _quota(u)}


@_locked
def plugin_token(email: str) -> str:
    """短时采集令牌，只给插件拉队列 / 回传，不含任何引擎密钥。未过期则复用。"""
    db = _load()
    now = time.time()
    plug = db.setdefault("plugin", {})
    db["plugin"] = {k: v for k, v in plug.items() if v.get("exp", 0) > now}
    for tok, rec in db["plugin"].items():
        if rec.get("email") == email and rec.get("exp", 0) > now + 60:
            return tok
    tok = secrets.token_urlsafe(16)
    db["plugin"][tok] = {"email": email, "at": now, "exp": now + 3600 * 8}
    _save(db)
    return tok


@_locked
def plugin_user(token: str | None) -> dict | None:
    if not token:
        return None
    db = _load()
    rec = (db.get("plugin") or {}).get(token)
    if not rec or rec.get("exp", 0) < time.time():
        return None
    return (db.get("users") or {}).get(rec["email"])


KEY_ENV_NAMES = (
    "ZHIPUAI_API_KEY", "ARK_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY",
    "MINIMAX_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "XAI_API_KEY", "PERPLEXITY_API_KEY",
)
