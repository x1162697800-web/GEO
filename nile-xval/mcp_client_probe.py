"""模拟一个 MCP 客户端，对 geolook 的 MCP server 走完整握手与工具调用。

单元测试是在进程内驱动 serve()，这里起真子进程走 stdio，验证的是
「客户端能不能真的连上」——手写协议层最大的风险就在这一层。
"""

import json
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "geolook" / "scripts" / "mcp_server.py"

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "1.0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "list_projects", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
     "params": {"name": "get_site_audit", "arguments": {"slug": "geolook"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
     "params": {"name": "get_method_reference", "arguments": {"section": "可抽取块"}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
     "params": {"name": "get_site_audit", "arguments": {"slug": "../escape"}}},
]

proc = subprocess.run(
    [sys.executable, str(SERVER)],
    input="\n".join(json.dumps(r, ensure_ascii=False) for r in REQS) + "\n",
    capture_output=True, text=True, encoding="utf-8", timeout=60,
    cwd=str(SERVER.parent.parent),
)

print(f"退出码: {proc.returncode}")
print(f"stderr: {proc.stderr.strip()[:200]}")
print()

resps = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
print(f"收到 {len(resps)} 条响应（发了 6 个请求 + 1 个通知，通知不该有响应）")
print()

by_id = {r.get("id"): r for r in resps}

r = by_id[1]["result"]
print(f"[1] initialize   协议版本 {r['protocolVersion']} · {r['serverInfo']['name']} {r['serverInfo']['version']}")

tools = by_id[2]["result"]["tools"]
print(f"[2] tools/list   {len(tools)} 个工具:")
for t in tools:
    print(f"       - {t['name']:22s} {t['description'][:46]}")

txt = by_id[3]["result"]["content"][0]["text"]
projects = json.loads(txt)
print(f"[3] list_projects  {len(projects)} 个项目: {[p['slug'] for p in projects]}")

a = json.loads(by_id[4]["result"]["content"][0]["text"])
print(f"[4] get_site_audit 均分 {a['avg_score']} · {a['page_count']} 页 · "
      f"四层 {[l['status'] for l in (a['layers'] or [])]}")

m = by_id[5]["result"]["content"][0]["text"]
print(f"[5] method_reference  取到 {len(m)} 字，首行: {m.splitlines()[0][:50]}")

r6 = by_id[6]["result"]
print(f"[6] 路径穿越 slug   isError={r6['isError']} · {r6['content'][0]['text'][:40]}")

ok = (proc.returncode == 0 and len(resps) == 6 and r6["isError"])
print()
print("全部通过" if ok else "有问题")
sys.exit(0 if ok else 1)
