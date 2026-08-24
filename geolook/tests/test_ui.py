import re
import unittest
from pathlib import Path

UI = Path(__file__).parent.parent / "scripts" / "ui.html"


class DocumentLangCase(unittest.TestCase):
    """回归：界面语言切换必须同步 <html lang>（WCAG 3.1.1，issue #1）。"""

    def setUp(self):
        self.html = UI.read_text("utf-8")

    def test_default_lang_is_zh_cn(self):
        self.assertIn('<html lang="zh-CN">', self.html)

    def test_ulang_updates_document_lang(self):
        m = re.search(
            r"document\.documentElement\.lang\s*=\s*(\{[^}]*\})\[ULANG\]", self.html
        )
        self.assertIsNotNone(m, "ULANG 未同步到 document.documentElement.lang")
        mapping = m.group(1)
        self.assertIn("zh:'zh-CN'", mapping)
        self.assertIn("en:'en'", mapping)
        self.assertIn("ja:'ja'", mapping)


class TrilingualCase(unittest.TestCase):
    """中文是 ui.html 的源语言，英/日靠 uiTranslate 覆盖层翻译。

    所以新增界面文案必须写成中文源串并补两份译文——写成英文源串在中文模式下
    会原样漏出（uiTranslate 在 ULANG==='zh' 时直接 return）。
    """

    def setUp(self):
        self.html = UI.read_text("utf-8")

    def test_language_switcher_present(self):
        self.assertIn("setLang(", self.html, "语言切换入口应存在")
        for code in ("'zh'", "'en'", "'ja'"):
            self.assertIn(code, self.html)

    def test_translation_layer_intact(self):
        for token in ("const UI_D", "const UI_SUB", "const UI_RX",
                      "function uiTranslate"):
            self.assertIn(token, self.html, f"缺少 {token}")

    def test_lang_query_param_supported(self):
        self.assertIn("get('lang')", self.html, "应支持 ?lang= 深链")

    def test_new_overview_strings_have_both_translations(self):
        """本轮新增的中文串在 en 与 ja 字典里都要有条目。"""
        keys = [
            "开始测 AI 可见性", "站点体检分", "阻塞层", "待办 P0",
            "最大内容缺口", "AI 可见性", "引擎接入", "立即跑采样",
            "这套部署还没配引擎接入", "还没有抓取任何页面",
        ]
        for k in keys:
            n = self.html.count(f"'{k}':'")
            self.assertGreaterEqual(n, 2, f"「{k}」缺英文或日文译文（找到 {n} 条）")


if __name__ == "__main__":
    unittest.main()
