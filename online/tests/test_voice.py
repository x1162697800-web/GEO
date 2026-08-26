import unittest

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

    def test_llms_txt_becomes_plain(self):
        self.assertIn("官方说明页", V.humanize("把 llms.txt 传到根目录"))
