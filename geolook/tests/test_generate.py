import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import generate as GEN


FACTS_FULL = """# 品牌事实卡

## 一句话定义

> GeoLook 是一个自托管的生成式引擎优化实施平台。

## 关键数字

| 事实 | 数值 | 来源 | 证据 |
|---|---|---|---|
| 支持引擎数 | 17 个 | 官网 | A |
| 自动验收率 | 86% | 样本项目 | B |
| 客服电话 | 待确认 | — | D |

**适合**：
- 需要把 GEO 落到执行的团队
- 代理商与咨询顾问

**不适合**：
- 只想看监控面板不想动手的团队
- 待确认的场景
"""

FACTS_EMPTY = """# 品牌事实卡

## 一句话定义

> 待确认
"""


def _project(root, slug="x", market="both", facts=FACTS_FULL, site="https://x.com"):
    pdir = Path(root) / slug
    (pdir / "content").mkdir(parents=True)
    cfg = {"brand": {"name": "GeoLook · Open", "site": site,
                     "aliases": ["GeoLook", "geolook"], "industry": "GEO 工具",
                     "target_users": "待确认",
                     "disambiguation": ["GEO 指生成式引擎优化，不是地理信息"]},
           "market": market, "questions": []}
    (pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
    if facts is not None:
        (pdir / "content" / "facts.md").write_text(facts, "utf-8")
    G.write_json(pdir / "audit.json", {"pages": [], "avg_score": 50, "page_count": 0})
    return pdir


class TestBrandSkill(unittest.TestCase):
    """品牌 SKILL.md：和 llms.txt / JSON-LD 并列的部署资产，描述的是被审计的品牌，
    不是 geolook 这个工具。两条纪律：只写已确认的事实、指向线上上下文。"""

    def test_frontmatter_is_single_line_and_parseable(self):
        """description 必须是单行双引号标量。

        用 >- 折叠标量时 YAML 拼行会插入空格，含空格的品牌名（GeoLook · Open）
        和中文都会被从中间撑开。
        """
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_skill_md("x", "zh")
        lines = out.split("\n")
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[1], "name: x")
        self.assertTrue(lines[2].startswith("description: \""))
        self.assertEqual(lines[3], "---", "frontmatter 必须正好 4 行，description 不许折行")
        desc = json.loads(lines[2][len("description: "):])
        self.assertIn("GeoLook · Open", desc, "品牌名不能被折行撑开")

    def test_unconfirmed_facts_are_dropped(self):
        """标「待确认」的事实一律不进——agent 会把这个文件当权威口径直接引用。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_skill_md("x", "zh")
        self.assertNotIn("待确认", out)
        self.assertNotIn("客服电话", out)      # 数值是「待确认」的整行丢弃
        self.assertNotIn("目标用户", out)      # brand 字段是「待确认」的也丢弃
        self.assertIn("支持引擎数: 17 个", out)  # 已确认的保留
        self.assertIn("需要把 GEO 落到执行的团队", out)

    def test_points_at_live_context_not_a_snapshot(self):
        """指向 llms.txt 而不是内嵌快照：事实库更新后已安装的 skill 要能看到新值。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_skill_md("x", "zh")
        self.assertIn("https://x.com/llms.txt", out)
        self.assertIn("冲突时以线上为准", out)

    def test_description_mentions_aliases_for_triggering(self):
        """description 决定 agent 何时加载这个 skill，必须含品牌名与别名。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                desc = json.loads(GEN.gen_skill_md("x", "zh").split("\n")[2][len("description: "):])
        for name in ("GeoLook · Open", "GeoLook", "geolook"):
            self.assertIn(name, desc)

    def test_empty_facts_yields_placeholder_not_fabrication(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, facts=FACTS_EMPTY)
                out = GEN.gen_skill_md("x", "zh")
        self.assertNotIn("待确认", out)
        self.assertIn("一句话定义尚未确认", out)

    def test_english_variant(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_skill_md("x", "en")
        self.assertIn("## Key facts", out)
        self.assertIn("Guardrails", out)
        self.assertNotIn("核心事实", out)


class TestSkillAssetWiring(unittest.TestCase):
    def test_market_controls_which_languages(self):
        for market, expect in (("cn", {"SKILL.md"}),
                               ("global", {"SKILL.en.md"}),
                               ("both", {"SKILL.md", "SKILL.en.md"})):
            with tempfile.TemporaryDirectory() as td:
                with mock.patch.object(G, "WORK", Path(td)):
                    _project(td, market=market)
                    GEN.run("x", which=["skill"])
                    got = {p.name for p in (Path(td) / "x" / "assets" / "skill").iterdir()}
            self.assertEqual(got, expect, f"market={market}")

    def test_skipped_without_own_site(self):
        """SKILL.md 的权威来源指向 llms.txt，没有自有域名就没有意义。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, site="")
                index = GEN.run("x", which=["skill"])
            self.assertEqual(index["assets"], [])
            self.assertFalse((Path(td) / "x" / "assets" / "skill").exists())

    def test_skill_is_in_default_asset_set(self):
        self.assertIn("skill", GEN.ASSETS)


if __name__ == "__main__":
    unittest.main()
