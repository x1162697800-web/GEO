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

# 英文事实卡：结构与中文对应，标题是英文的
FACTS_EN = """# Brand facts

## One-line definition

> Grounded is a self-hosted platform for generative engine optimization.

## Key numbers

| Fact | Value | Source | Evidence |
|---|---|---|---|
| Engines supported | 17 | Website | A |
| Phone | TBD | — | D |

**Good fit**:
- Teams that need GEO turned into execution

**Not a fit**:
- Teams that only want a dashboard
"""


def _project(root, slug="x", market="both", facts=FACTS_FULL, site="https://x.com",
             facts_en=None, brand_en=None, questions=None):
    pdir = Path(root) / slug
    (pdir / "content").mkdir(parents=True)
    brand = {"name": "Grounded · Open", "site": site,
             "aliases": ["Grounded", "grounded"], "industry": "GEO 工具",
             "target_users": "待确认",
             "disambiguation": ["GEO 指生成式引擎优化，不是地理信息"]}
    if brand_en is not None:
        brand["en"] = brand_en
    cfg = {"brand": brand, "market": market, "questions": questions or []}
    (pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
    if facts is not None:
        (pdir / "content" / "facts.md").write_text(facts, "utf-8")
    if facts_en is not None:
        (pdir / "content" / "facts.en.md").write_text(facts_en, "utf-8")
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
        """主语言用无后缀名，次语言加后缀——所以 global 项目也叫 SKILL.md。"""
        for market, expect in (("cn", {"SKILL.md"}),
                               ("global", {"SKILL.md"}),
                               ("both", {"SKILL.md", "SKILL.en.md"})):
            with tempfile.TemporaryDirectory() as td:
                with mock.patch.object(G, "WORK", Path(td)):
                    _project(td, market=market)
                    GEN.run("x", which=["skill"])
                    got = {p.name for p in (Path(td) / "x" / "assets" / "skill").iterdir()}
            self.assertEqual(got, expect, f"market={market}")

    def test_global_skill_md_is_english(self):
        """global 项目的 SKILL.md 不带后缀，但内容必须是英文的。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, market="global")
                GEN.run("x", which=["skill"])
                body = (Path(td) / "x" / "assets" / "skill" / "SKILL.md").read_text("utf-8")
        self.assertIn("## Key facts", body)
        self.assertNotIn("## 核心事实", body)

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


class TestEnglishAssetsCarryNoChineseFacts(unittest.TestCase):
    """英文资产不能是「英文标签套中文内容」。

    回归自实跑：market=global 的项目拿到的 llms.en.txt 里是
    `- Industry: GEO 工具`。这些文件传到客户公网站点、由爬虫直读，
    透传中文等于把中文事实当成英文语境下的权威口径发出去。

    纪律：英文事实只能来自人工撰写的 facts.en.md 与 brand.en；缺失就留空，
    绝不透传，也绝不机器翻译——翻错的品牌声明就是编造的声明。
    """

    def test_en_facts_come_from_facts_en_md(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, facts_en=FACTS_EN)
                out = GEN.gen_llms_txt("x", "en")
        self.assertIn("Grounded is a self-hosted platform", out)
        self.assertIn("Engines supported: 17", out)
        self.assertNotIn("TBD", out)                    # 未确认的照样过滤
        self.assertNotIn("自托管", out)                  # 中文定义句不能串进来

    def test_en_ignores_chinese_facts_md_entirely(self):
        """只有中文事实卡时，英文资产宁可空着也不透传。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)                            # 只有 facts.md
                out = GEN.gen_llms_txt("x", "en")
        self.assertNotIn("支持引擎数", out)
        self.assertNotIn("自托管", out)
        self.assertIn("One-line definition not confirmed yet", out)

    def test_en_brand_prose_requires_brand_en(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)                            # industry 是中文「GEO 工具」
                out = GEN.gen_llms_txt("x", "en")
        self.assertNotIn("GEO 工具", out)
        self.assertNotIn("Industry:", out, "没有英文行业说法就该整行不出")
        self.assertNotIn("生成式引擎优化", out)          # 中文消歧句同样不能进

    def test_en_brand_prose_used_when_provided(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, brand_en={"industry": "GEO tooling",
                                       "target_users": "In-house SEO teams",
                                       "disambiguation": ["GEO here means generative engine optimization."]})
                out = GEN.gen_llms_txt("x", "en")
        self.assertIn("Industry: GEO tooling", out)
        self.assertIn("For: In-house SEO teams", out)
        self.assertIn("generative engine optimization", out)
        self.assertNotIn("GEO 工具", out)

    def test_zh_assets_unchanged_by_brand_en(self):
        """brand.en 只服务英文产物，不能影响中文产物。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, brand_en={"industry": "GEO tooling"})
                out = GEN.gen_llms_txt("x", "zh")
        self.assertIn("行业: GEO 工具", out)
        self.assertNotIn("GEO tooling", out)

    def test_skill_en_carries_no_chinese_facts(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_skill_md("x", "en")
        self.assertNotIn("GEO 工具", out)
        self.assertNotIn("支持引擎数", out)
        self.assertNotIn("、", out, "英文产物不该出现顿号分隔的别名")

    def test_definition_snippet_en_carries_no_chinese(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td)
                out = GEN.gen_definition_block("x", "en")
        self.assertNotIn("生成式引擎优化", out)
        self.assertIn("(definition TBD)", out)


class TestJsonldFollowsMarket(unittest.TestCase):
    """JSON-LD 贴进客户页面 <head>，语言必须跟着市场走。"""

    QS = [{"text": "GEO 是什么", "market": "cn"},
          {"text": "What is GEO", "market": "global"}]

    def test_en_faq_uses_global_questions(self):
        """回归：FAQ 筛选曾写死 ("cn","both")，global 项目会拿中文问答填英文页面。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, questions=self.QS)
                out = GEN.gen_jsonld("x", "en")
        names = [q["name"] for q in out["faq-page"]["mainEntity"]]
        self.assertEqual(names, ["What is GEO"])

    def test_zh_faq_uses_cn_questions(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, questions=self.QS)
                out = GEN.gen_jsonld("x", "zh")
        names = [q["name"] for q in out["faq-page"]["mainEntity"]]
        self.assertEqual(names, ["GEO 是什么"])

    def test_en_jsonld_has_no_chinese_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, questions=self.QS)
                out = GEN.gen_jsonld("x", "en")
        blob = json.dumps(out, ensure_ascii=False)
        for bad in ("填", "首页", "栏目", "CNY"):
            self.assertNotIn(bad, blob, f"英文 JSON-LD 里残留「{bad}」")

    def test_market_controls_jsonld_variants(self):
        """只有 market=both 才有第二语言变体；单市场项目一律无后缀。"""
        for market, expect_en_suffix in (("cn", False), ("global", False), ("both", True)):
            with tempfile.TemporaryDirectory() as td:
                with mock.patch.object(G, "WORK", Path(td)):
                    _project(td, market=market)
                    GEN.run("x", which=["jsonld"])
                    got = {p.name for p in (Path(td) / "x" / "assets" / "jsonld").iterdir()}
            self.assertEqual(any(n.endswith(".en.json") for n in got), expect_en_suffix,
                             f"market={market}：{sorted(got)}")
            self.assertIn("organization.json", got, f"market={market}：{sorted(got)}")

    def test_global_jsonld_is_english_under_the_plain_name(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, market="global", questions=self.QS)
                GEN.run("x", which=["jsonld"])
                d = Path(td) / "x" / "assets" / "jsonld"
                faq = json.loads((d / "faq-page.json").read_text("utf-8"))
        self.assertEqual([q["name"] for q in faq["mainEntity"]], ["What is GEO"])

    def test_narrowing_market_cleans_stale_language_variants(self):
        """both → cn 之后，英文 JSON-LD 必须消失，否则会被打进交付包。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                pdir = _project(td, market="both")
                GEN.run("x", which=["jsonld"])
                d = pdir / "assets" / "jsonld"
                self.assertTrue(any(p.name.endswith(".en.json") for p in d.iterdir()))

                cfg = json.loads((pdir / "geo.json").read_text("utf-8"))
                cfg["market"] = "cn"
                (pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
                GEN.run("x", which=["jsonld"])
                left = {p.name for p in d.iterdir()}
        self.assertFalse(any(n.endswith(".en.json") for n in left), sorted(left))
        self.assertIn("organization.json", left)


class TestCanonicalLlmsTxtPath(unittest.TestCase):
    """llms.txt 必须落在规范路径 /llms.txt，主语言不加后缀。

    回归：market=global 的项目原先只产 llms.en.txt，而 DEPLOY.md 教客户传
    `assets/llms.txt`——那个文件不存在，站点根目录永远缺 /llms.txt，
    接着自家审计又会因为「没有 /llms.txt」扣分。自己教的部署过不了自己的体检。
    """

    def _names(self, td, market):
        with mock.patch.object(G, "WORK", Path(td)):
            _project(td, market=market)
            GEN.run("x", which=["llms"])
            return {p.name for p in (Path(td) / "x" / "assets").iterdir() if p.is_file()}

    def test_every_market_produces_plain_llms_txt(self):
        for market in ("cn", "global", "both"):
            with tempfile.TemporaryDirectory() as td:
                got = self._names(td, market)
            self.assertIn("llms.txt", got, f"market={market}：{sorted(got)}")

    def test_only_both_gets_a_second_variant(self):
        for market, expect in (("cn", False), ("global", False), ("both", True)):
            with tempfile.TemporaryDirectory() as td:
                got = self._names(td, market)
            self.assertEqual("llms.en.txt" in got, expect, f"market={market}：{sorted(got)}")

    def test_global_plain_llms_txt_is_english(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                _project(td, market="global", facts_en=FACTS_EN)
                GEN.run("x", which=["llms"])
                body = (Path(td) / "x" / "assets" / "llms.txt").read_text("utf-8")
        self.assertIn("## Key facts", body)
        self.assertNotIn("## 核心事实", body)

    def test_switching_market_leaves_no_orphan_variant(self):
        """both → global：英文从 .en 升为主名，旧的 llms.en.txt 不能留下。"""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(G, "WORK", Path(td)):
                pdir = _project(td, market="both")
                GEN.run("x", which=["llms"])
                self.assertTrue((pdir / "assets" / "llms.en.txt").exists())

                cfg = json.loads((pdir / "geo.json").read_text("utf-8"))
                cfg["market"] = "global"
                (pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
                GEN.run("x", which=["llms"])
                left = {p.name for p in (pdir / "assets").iterdir() if p.is_file()}
        self.assertEqual(left, {"llms.txt", "index.json"}, sorted(left))


if __name__ == "__main__":
    unittest.main()
