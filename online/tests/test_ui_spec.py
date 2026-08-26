import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app.html"
SERVER = Path(__file__).resolve().parent.parent / "server.py"


class SpecNavCase(unittest.TestCase):
    """执行文档第 13 节：左侧只有总览、该做什么、效果、报告（外加设置）。"""

    def setUp(self):
        self.html = APP.read_text("utf-8")

    def test_four_plus_settings(self):
        self.assertIn('["overview","总览"]', self.html)
        self.assertIn('["plan","该做什么"]', self.html)
        self.assertIn('["effect","效果"]', self.html)
        self.assertIn('["report","报告"]', self.html)
        self.assertIn("设置", self.html)

    def test_plugin_not_in_nav(self):
        nav = re.search(r"const NAV=(\[[^\]]+\])", self.html).group(1)
        self.assertNotIn("插件", nav)

    def test_no_key_form(self):
        self.assertNotIn("ZHIPUAI", self.html)
        self.assertNotIn("OPENAI_API_KEY", self.html)
        self.assertNotIn('type="password" placeholder', self.html)
        # 可以提到「不填 Key」，但不能出现密钥输入框
        self.assertNotIn('id="api_key"', self.html)

    def test_unmeasured_copy_exists(self):
        self.assertIn("还没测", self.html)
        self.assertIn("没有样本时不写成 0", self.html)

    def test_server_never_serves_key_form(self):
        src = SERVER.read_text("utf-8")
        self.assertNotIn("write_env", src)
        self.assertIn("_strip_secrets", src)
