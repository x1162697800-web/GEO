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

> Grounded 是一个自托管的生成式引擎优化实施平台。

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
    cfg = {"brand": {"name": "Grounded · Open", "site": site,
                     "aliases": ["Grounded", "grounded"], "industry": "GEO 工具",
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
    不是 grounded 这个工具。两条纪律：只写已确认的事实、指向线上上下文。"""

    def test_frontmatter_is_single_line_and_parseable(self):
        """description 必须是单行双引号标量。

        用 >- 折叠标量时 YAML 拼行会插入空格，含空格的品牌名（Grounded · Open）
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
        self.assertIn("Grounded · Open", desc, "品牌名不能被折行撑开")

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
        for name in ("Grounded · Open", "Grounded", "grounded"):
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


class TestUnconfirmedFactsNeverShipped(unittest.TestCase):
    """凡是 AI 会直接读到的产物都不许带「待确认」。

    回归自实跑：llms.txt 曾经把「商务电话: 待确认」发出去。它传到网站根目录
    由爬虫读取，占位符会被当成权威事实——比在 SKILL.md 里更严重。
    """

    def test_llms_txt_drops_unconfirmed_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_llms_txt("x", "zh")
        self.assertNotIn("待确认", out)
        self.assertNotIn("客服电话", out)
        self.assertIn("支持引擎数: 17 个", out)      # 已确认的保留

    def test_llms_txt_drops_unconfirmed_brand_fields(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)                        # target_users 是「待确认」
                out = GEN.gen_llms_txt("x", "zh")
        self.assertNotIn("目标用户", out)
        self.assertIn("行业", out)                   # 已确认的保留

    def test_llms_txt_english_variant_also_filters(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_llms_txt("x", "en")
        self.assertNotIn("待确认", out)
        self.assertNotIn("For:", out)               # target_users 未确认

    def test_llms_txt_never_quotes_an_unconfirmed_definition(self):
        """定义句未确认时不能写成引用块——爬虫会把它当权威定义抄走。

        回归自实跑：wagnab 的 llms.en.txt 首行是
        「> （待补：一句话定义…）」——占位符 + 中文，两重错误。
        """
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, facts=FACTS_EMPTY)
                out = GEN.gen_llms_txt("x", "zh")
        self.assertNotIn("待确认", out)
        self.assertNotIn("待补", out)
        for line in out.splitlines():
            self.assertFalse(line.startswith(">"), f"未确认的定义句仍被写成引用块：{line}")

    def test_llms_txt_en_placeholder_is_not_chinese(self):
        """英文资产传到客户网站根目录，占位提示必须也是英文。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, facts=FACTS_EMPTY)
                out = GEN.gen_llms_txt("x", "en")
        self.assertIn("One-line definition not confirmed yet", out)
        self.assertNotIn("一句话定义", out)
        self.assertNotIn("待补", out)

    def test_jsonld_description_drops_unconfirmed_definition(self):
        """JSON-LD 贴进 <head> 给爬虫读，未确认的定义句不能进 description。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, facts=FACTS_EMPTY)     # 定义句是「待确认」
                out = GEN.gen_jsonld("x")
        for name, obj in out.items():
            self.assertNotIn("待确认", json.dumps(obj, ensure_ascii=False), name)
        self.assertEqual(out["organization"]["description"], "")

    def test_definition_snippet_filters_numbers_but_keeps_placeholder(self):
        """片段贴进真实页面：数字要过滤；定义句缺失时的占位符是给人看的提示，保留。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, facts=FACTS_EMPTY)
                out = GEN.gen_definition_block("x", "zh")
        self.assertIn("（待补定义句）", out, "显式占位符应保留")
        self.assertNotIn("待确认", out, "未确认的数字不能进页面片段")

    def test_definition_snippet_keeps_confirmed_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_definition_block("x", "zh")
        self.assertIn("17 个", out)
        self.assertNotIn("待确认", out)


class TestNoEmptyFaqSchema(unittest.TestCase):
    """空的 FAQPage 是负信号，不是无害的空壳。

    按 audit.py 的 SCHEMA_CONTENT_MISMATCH：声明了 FAQPage 却没有可见问答，
    检索系统拿可见文本对账时会扣分。geolook 不该产出自己会判罚的资产。
    """

    def test_faq_page_omitted_when_no_questions(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)                        # questions 为空
                out = GEN.gen_jsonld("x")
        self.assertNotIn("faq-page", out, "问题库为空时不应产出 FAQPage")
        self.assertIn("organization", out)          # 其他 schema 照常

    def test_faq_page_present_when_questions_exist(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                p = _project(td)
                cfg = json.loads((p / "geo.json").read_text("utf-8"))
                cfg["questions"] = [{"id": "Q1", "text": "什么是 X", "market": "cn"}]
                (p / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
                out = GEN.gen_jsonld("x")
        self.assertIn("faq-page", out)
        self.assertTrue(out["faq-page"]["mainEntity"], "mainEntity 不能是空的")

    def test_generated_faq_file_absent_on_disk(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                GEN.run("x", which=["jsonld"])
                names = {f.name for f in (Path(td) / "x" / "assets" / "jsonld").iterdir()}
        self.assertNotIn("faq-page.json", names)

    def test_stale_jsonld_is_removed_on_regeneration(self):
        """生成器要对「不再产出」也幂等。

        回归自实跑：问题库清空后 FAQPage 不再生成，但旧的 faq-page.json 留在
        assets/ 里，被原样打进交付包发给客户。
        """
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                p = _project(td)
                cfg = json.loads((p / "geo.json").read_text("utf-8"))
                cfg["questions"] = [{"id": "Q1", "text": "什么是 X", "market": "cn"}]
                (p / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
                GEN.run("x", which=["jsonld"])
                jd = p / "assets" / "jsonld"
                self.assertTrue((jd / "faq-page.json").exists(), "有问题时应产出")

                cfg["questions"] = []               # 清空问题库后重跑
                (p / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
                GEN.run("x", which=["jsonld"])
                self.assertFalse((jd / "faq-page.json").exists(), "旧文件应被清掉")
                self.assertTrue((jd / "organization.json").exists(), "其他文件不受影响")

    def test_user_added_asset_files_are_not_deleted(self):
        """资产页允许用户手动加文件，清理范围必须限定在生成器认领的名字内。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                p = _project(td)
                GEN.run("x", which=["jsonld"])
                mine = p / "assets" / "jsonld" / "my-custom-schema.json"
                mine.write_text('{"@type":"Thing"}', "utf-8")
                GEN.run("x", which=["jsonld"])
                self.assertTrue(mine.exists(), "用户自己加的文件不能被删")


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
