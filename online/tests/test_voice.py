import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import voice as V


class VoiceCase(unittest.TestCase):
    def test_priority_bands(self):
        self.assertEqual(V.band("P0"), "先做")
        self.assertEqual(V.band("P1"), "接着做")
        self.assertEqual(V.band("P2"), "可以后做")

    def test_unmeasured_is_none_not_zero(self):
        self.assertIsNone(V.pct_or_unmeasured(None))
        self.assertEqual(V.pct_or_unmeasured(0.0), "0%")

    def test_spa_and_entity_jargon_leave(self):
        t = V.humanize("修复前端渲染空壳页（SSR / 预渲染）。实体消歧要先做。")
        self.assertNotIn("SSR", t)
        self.assertNotIn("实体消歧", t)
        self.assertIn("我们是谁", t)

    def test_route_ssr_sentence(self):
        t = V.humanize("对受影响路由启用 SSR 或预渲染，确保 curl 拿到的 HTML 含完整正文")
        self.assertNotIn("SSR", t)
        self.assertNotIn("curl", t)
        self.assertIn("打开后就能读到正文", t)

    def test_llms_txt_becomes_plain(self):
        self.assertIn("官方说明页", V.humanize("把 llms.txt 传到根目录"))

    def test_consultant_doc_refs_leave(self):
        t = V.humanize("口径不一致（content-patterns.md 第 6 节）。参照 content-patterns.md，补定义块")
        self.assertNotIn(".md", t)
        self.assertNotIn("content-patterns", t)
