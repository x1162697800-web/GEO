import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import mcp_proto as P
import mcp_server as S


def _drive(lines: list[dict]) -> list[dict]:
    """把若干请求喂给 serve()，收集 stdout 上的响应。"""
    stdin = io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n")
    out = io.StringIO()
    with mock.patch.object(sys, "stdout", out):
        P.serve("geolook", "test", S.TOOLS, stream=stdin)
    return [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]


def _req(mid, method, params=None):
    m = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        m["params"] = params
    return m


def _project(root, slug="demo"):
    p = Path(root) / slug
    (p / "content").mkdir(parents=True)
    (p / "geo.json").write_text(json.dumps(
        {"brand": {"name": "Demo", "site": "https://demo.test"}, "market": "cn",
         "questions": [{"id": "Q1", "text": "什么是 X", "intent": "educate"},
                       {"id": "Q2", "text": "X 多少钱", "intent": "buyer"}]},
        ensure_ascii=False), "utf-8")
    G.write_json(p / "audit.json", {"avg_score": 42.0, "page_count": 3,
                                    "grade_distribution": {"D": 3},
                                    "layers": [{"key": "access", "status": "fail"}],
                                    "site": {"has_robots": True, "ai_ua_blocked": []},
                                    "pages": [{"url": "u", "score": 42, "grade": "D"}]})
    G.write_json(p / "tasks.json", {"tasks": [
        {"id": "T-001", "priority": "P0", "risk": "high", "title": "修 SSR",
         "status": "todo", "acceptance": {"type": "auto"}},
        {"id": "T-002", "priority": "P2", "risk": "low", "title": "补 FAQ",
         "status": "done", "acceptance": {"type": "manual"}}]})
    return p


class TestProtocol(unittest.TestCase):
    def test_initialize_handshake(self):
        r = _drive([_req(1, "initialize", {"protocolVersion": "2024-11-05"})])[0]
        self.assertEqual(r["id"], 1)
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "geolook")

    def test_unknown_protocol_version_falls_back_to_ours(self):
        r = _drive([_req(1, "initialize", {"protocolVersion": "1999-01-01"})])[0]
        self.assertEqual(r["result"]["protocolVersion"], P.PROTOCOL_VERSION)

    def test_notifications_get_no_response(self):
        out = _drive([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertEqual(out, [])

    def test_tools_list_shape(self):
        r = _drive([_req(2, "tools/list")])[0]
        tools = r["result"]["tools"]
        self.assertTrue(tools)
        for t in tools:
            self.assertIn("name", t)
            self.assertIn("description", t)
            self.assertIn("inputSchema", t)
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_malformed_json_does_not_kill_server(self):
        stdin = io.StringIO("not json\n" + json.dumps(_req(3, "tools/list")) + "\n")
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            P.serve("geolook", "test", S.TOOLS, stream=stdin)
        got = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
        self.assertEqual(got[0]["error"]["code"], P.PARSE_ERROR)
        self.assertEqual(got[1]["id"], 3)  # 后一条仍被正常处理

    def test_unknown_method(self):
        r = _drive([_req(4, "no/such/method")])[0]
        self.assertEqual(r["error"]["code"], P.METHOD_NOT_FOUND)

    def test_unknown_tool(self):
        r = _drive([_req(5, "tools/call", {"name": "nope", "arguments": {}})])[0]
        self.assertEqual(r["error"]["code"], P.INVALID_PARAMS)

    def test_tool_error_is_a_normal_result_with_isError(self):
        """工具报错要让模型看得到原因，不能变成协议级错误。"""
        r = _drive([_req(6, "tools/call",
                         {"name": "get_site_audit", "arguments": {"slug": "nope"}})])[0]
        self.assertNotIn("error", r)
        self.assertTrue(r["result"]["isError"])
        self.assertIn("nope", r["result"]["content"][0]["text"])

    def test_system_exit_from_die_does_not_kill_server(self):
        """geolib.die() 走 sys.exit，长驻服务里必须被拦住。"""
        boom = P.Tool("boom", "d", {"type": "object", "properties": {}},
                      lambda: (_ for _ in ()).throw(SystemExit("模拟 die")))
        stdin = io.StringIO(json.dumps(_req(7, "tools/call",
                                            {"name": "boom", "arguments": {}})) + "\n")
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            P.serve("geolook", "test", [boom], stream=stdin)
        r = json.loads(out.getvalue().strip())
        self.assertTrue(r["result"]["isError"])
        self.assertIn("模拟 die", r["result"]["content"][0]["text"])


class TestToolBehaviour(unittest.TestCase):
    def _call(self, name, args=None):
        r = _drive([_req(9, "tools/call", {"name": name, "arguments": args or {}})])[0]
        self.assertNotIn("error", r, r)
        txt = r["result"]["content"][0]["text"]
        self.assertFalse(r["result"]["isError"], txt)
        return json.loads(txt) if txt.lstrip()[:1] in "[{" else txt

    def test_list_and_read_project(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                projects = self._call("list_projects")
                self.assertEqual(projects[0]["slug"], "demo")
                self.assertEqual(projects[0]["avg_score"], 42.0)
                self.assertEqual(projects[0]["tickets_open"], 1)

                audit = self._call("get_site_audit", {"slug": "demo"})
                self.assertEqual(audit["avg_score"], 42.0)
                self.assertEqual(audit["layers"][0]["status"], "fail")

                tickets = self._call("list_tickets", {"slug": "demo", "status": "todo"})
                self.assertEqual(len(tickets["tickets"]), 1)
                self.assertEqual(tickets["tickets"][0]["risk"], "high")

                qs = self._call("get_question_bank", {"slug": "demo", "intent": "buyer"})
                self.assertEqual([q["id"] for q in qs], ["Q2"])

    def test_slug_whitelist_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                for bad in ("../etc", "a/b", "..", "x" * 60, ""):
                    r = _drive([_req(1, "tools/call",
                                     {"name": "get_site_audit",
                                      "arguments": {"slug": bad}})])[0]
                    self.assertTrue(r["result"]["isError"], f"{bad!r} 应被拒绝")

    def test_generate_rejects_unknown_asset(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                r = _drive([_req(1, "tools/call",
                                 {"name": "generate_assets",
                                  "arguments": {"slug": "demo", "assets": "llms,evil"}})])[0]
                self.assertTrue(r["result"]["isError"])
                self.assertIn("evil", r["result"]["content"][0]["text"])


class TestMethodReference(unittest.TestCase):
    MD = "\n".join([
        "# 方法层", "开头", "",
        "## 2. 评分口径", "总述", "",
        "### 可抽取块（25）", "定义 6、数字 6", "",
        "### 权威信号（15）", "日期、作者", "",
        "## 3. 内容工程铁律", "写成证据页", ""])

    def _ref(self, section=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "references" / "method.md").write_text(self.MD, "utf-8")
            with mock.patch.object(G, "ROOT", root):
                return S.get_method_reference(section)

    def test_matches_h3_not_just_h2(self):
        """六维里「可抽取块」是 H3——只切 H2 会漏掉，这是实测撞到的 bug。"""
        out = self._ref("可抽取块")
        self.assertIn("### 可抽取块（25）", out)
        self.assertIn("定义 6、数字 6", out)
        self.assertNotIn("权威信号", out, "应止于下一个同级标题")

    def test_h2_section_includes_its_h3_children(self):
        out = self._ref("评分口径")
        self.assertIn("可抽取块", out)
        self.assertIn("权威信号", out)
        self.assertNotIn("内容工程铁律", out)

    def test_no_section_returns_everything(self):
        self.assertEqual(self._ref(), self.MD)

    def test_miss_lists_available_titles(self):
        with self.assertRaises(P.ToolError) as cm:
            self._ref("不存在的东西")
        self.assertIn("可抽取块", str(cm.exception))


class TestSecurityBoundary(unittest.TestCase):
    """这些边界是有意的，放宽前先读 mcp_server.py 顶部说明。"""

    def test_no_publish_tool(self):
        names = {t.name for t in S.TOOLS}
        for forbidden in ("publish", "publish_content", "deliver", "send"):
            self.assertNotIn(forbidden, names)
        self.assertFalse([n for n in names if "publish" in n],
                         "发布必须由人显式确认，不能给 agent")

    def test_no_crawl_tool(self):
        """抓取会请求第三方站点，由 agent 驱动的网络副作用风险太高。"""
        self.assertFalse([t.name for t in S.TOOLS if "crawl" in t.name])

    def test_write_tools_are_marked(self):
        by_name = {t.name: t for t in S.TOOLS}
        self.assertEqual({n for n, t in by_name.items() if t.writes},
                         {"run_audit", "generate_assets"})

    def test_no_secrets_in_any_read_tool_output(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                p = _project(td)
                # 项目目录里放一份假密钥，确认任何工具都不会把它带出去
                (p / "geo.json").write_text(json.dumps(
                    {"brand": {"name": "Demo", "site": "https://demo.test"},
                     "market": "cn", "questions": [],
                     "secret_key": "sk-must-never-leak"}, ensure_ascii=False), "utf-8")
                blob = json.dumps([
                    S.list_projects(),
                    S.list_tickets("demo"),
                    S.get_question_bank("demo"),
                ], ensure_ascii=False)
        self.assertNotIn("sk-must-never-leak", blob)


if __name__ == "__main__":
    unittest.main()
