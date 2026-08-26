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
