"""MCP 协议层：stdio 上的 JSON-RPC 2.0。不含任何 grounded 业务知识。

手写而不是用官方 SDK：SDK 会带进 pydantic / anyio / httpx 一串传递依赖，
破坏 README 里「恰好三个第三方包」这个定位。协议面很窄——initialize 握手、
tools/list、tools/call——标准库的 json + sys.stdin/stdout 就够。
这与 dashboard 用标准库 http.server 而不是 Flask 是同一条路。

**单独成模块是有意的**：规范剧烈变动时可以整体换成官方 SDK，
工具实现（mcp_server.py）不用动一行。

传输约定：stdout 只放 JSON-RPC 响应，日志一律走 stderr——
混进一行别的东西就会把客户端的解析打断。
"""

from __future__ import annotations

import json
import sys
import traceback

# 我们声明的版本。客户端请求的版本在这个集合里就原样回声，
# 否则回自己的版本让客户端决定是否继续（MCP 的协商约定）。
PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ToolError(Exception):
    """工具主动报错：会变成 isError 的正常响应，而不是协议级错误。"""


class Tool:
    def __init__(self, name: str, description: str, schema: dict, handler,
                 writes: bool = False):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.writes = writes  # 会不会改 work/ 下的数据，供调用方审计

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description,
                "inputSchema": self.schema}


def _log(msg: str):
    print(f"[mcp] {msg}", file=sys.stderr, flush=True)


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(req_id, result: dict):
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str):
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _text_result(req_id, text: str, is_error: bool = False):
    _result(req_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


def handle(msg: dict, registry: dict[str, Tool], server_name: str, version: str):
    """处理一条消息。通知（无 id）不回响应。"""
    req_id = msg.get("id")
    method = msg.get("method")
    is_notification = req_id is None

    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        ver = want if want in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        return _result(req_id, {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": server_name, "version": version},
        })

    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return  # 通知，不回

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": [t.spec() for t in registry.values()]})

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        tool = registry.get(name)
        if not tool:
            return _error(req_id, INVALID_PARAMS, f"未知工具：{name}")
        args = params.get("arguments") or {}
        try:
            out = tool.handler(**args)
        except ToolError as e:
            # 工具主动报错 → 正常响应里标 isError，让模型能看到原因并自行纠正
            return _text_result(req_id, str(e), is_error=True)
        except TypeError as e:
            return _error(req_id, INVALID_PARAMS, f"参数不对：{e}")
        except SystemExit as e:
            # geolib.die() 走的是 sys.exit——在长驻服务里绝不能让它把进程带走
            return _text_result(req_id, f"操作中止：{e}", is_error=True)
        except Exception as e:  # noqa: BLE001  单个工具崩了不该拖垮服务
            _log(f"工具 {name} 异常：{traceback.format_exc()}")
            return _text_result(req_id, f"{type(e).__name__}: {e}", is_error=True)
        if not isinstance(out, str):
            out = json.dumps(out, ensure_ascii=False, indent=2)
        return _text_result(req_id, out)

    if is_notification:
        return
    _error(req_id, METHOD_NOT_FOUND, f"未实现的方法：{method}")


def serve(server_name: str, version: str, tools: list[Tool], stream=None):
    registry = {t.name: t for t in tools}
    _log(f"{server_name} {version} 就绪，{len(registry)} 个工具（stdio）")
    for line in (stream or sys.stdin):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _error(None, PARSE_ERROR, f"JSON 解析失败：{e}")
            continue
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            _error(msg.get("id") if isinstance(msg, dict) else None,
                   INVALID_REQUEST, "不是合法的 JSON-RPC 2.0 消息")
            continue
        try:
            handle(msg, registry, server_name, version)
        except Exception:  # noqa: BLE001  协议层自身出错也不能让服务死掉
            _log(f"分发异常：{traceback.format_exc()}")
            if msg.get("id") is not None:
                _error(msg["id"], INTERNAL_ERROR, "服务端内部错误，详见 stderr")
