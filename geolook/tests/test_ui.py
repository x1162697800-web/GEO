import re
import unittest
from pathlib import Path

UI = Path(__file__).parent.parent / "scripts" / "ui.html"


class DocumentLangCase(unittest.TestCase):
    """回归：<html lang> 必须与实际内容语言一致（WCAG 3.1.1，issue #1）。

    界面已改为英文单语，所以规则不变、取值变了：静态属性和运行时都必须是 en。
    """

    def setUp(self):
        self.html = UI.read_text("utf-8")

    def test_static_lang_is_english(self):
        self.assertIn('<html lang="en">', self.html)
        self.assertNotIn('<html lang="zh-CN">', self.html)

    def test_runtime_lang_matches_static(self):
        m = re.search(r"document\.documentElement\.lang\s*=\s*'([\w-]+)'", self.html)
        self.assertIsNotNone(m, "运行时未设置 document.documentElement.lang")
        self.assertEqual(m.group(1), "en", "运行时语言必须与 <html lang> 一致")


class SingleLanguageCase(unittest.TestCase):
    """英文单语：不能再有语言切换入口。

    翻译覆盖层（UI_D / UI_SUB / UI_RX / uiTranslate）暂时保留——后端仍产出中文，
    删掉会让体检问题、工单文案等退回原始中文。后端源串英文化后一并移除。
    """

    def setUp(self):
        self.html = UI.read_text("utf-8")

    def test_no_language_switcher(self):
        self.assertNotIn("setLang(", self.html, "语言切换入口应已移除")

    def test_ulang_is_pinned_to_english(self):
        m = re.search(r"const ULANG\s*=\s*'([\w-]+)'", self.html)
        self.assertIsNotNone(m, "ULANG 应为写死的常量")
        self.assertEqual(m.group(1), "en")

    def test_no_lang_query_param_handling(self):
        self.assertNotIn("get('lang')", self.html, "不应再从 URL 读取语言参数")


if __name__ == "__main__":
    unittest.main()
