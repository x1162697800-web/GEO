import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "geolook" / "scripts"))

import account as ACC  # noqa: E402
import present as P  # noqa: E402
import server as SV  # noqa: E402
import voice as V  # noqa: E402


class QuotaCase(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self._old_data = ACC.DATA
        self._old_acc = ACC.ACCOUNTS
        ACC.DATA = Path(self.td.name)
        ACC.ACCOUNTS = ACC.DATA / "accounts.json"

    def tearDown(self):
        ACC.DATA = self._old_data
        ACC.ACCOUNTS = self._old_acc
        self.td.cleanup()

    def test_saver_blocks_on_second_run(self):
        r = ACC.register("a@x.com", "secret1", "A")
        self.assertTrue(r["ok"])
        u = ACC.user_of(r["token"])
        self.assertEqual(ACC.estimate(u)["quota"]["cap"], 1)
        self.assertFalse(ACC.estimate(u)["blocked"])
        ACC.consume("a@x.com")
        u = ACC.user_of(r["token"])
        est = ACC.estimate(u)
        self.assertTrue(est["blocked"])
        self.assertEqual(est["block_reason"], "本月次数用完")
        again = ACC.consume("a@x.com")
        self.assertFalse(again["ok"])
        self.assertEqual(again["error"], "本月次数用完")

    def test_refund_restores_one_run(self):
        ACC.register("c@x.com", "secret1")
        ACC.consume("c@x.com")
        ACC.refund("c@x.com")
        u = ACC.user_of(ACC.login("c@x.com", "secret1")["token"])
        self.assertFalse(ACC.estimate(u)["blocked"])

    def test_no_keys_in_public_user(self):
        r = ACC.register("b@x.com", "secret1")
        blob = json.dumps(ACC.public_user(ACC.user_of(r["token"])))
        for k in ACC.KEY_ENV_NAMES:
            self.assertNotIn(k, blob)

    def test_report_link_is_read_only_and_expires_separately(self):
        ACC.register("share@x.com", "secret1")
        ACC.attach_project("share@x.com", "demo")
        token = ACC.report_token("share@x.com", "demo")
        self.assertTrue(token)
        self.assertEqual(ACC.report_access(token)["slug"], "demo")


class DemoGateCase(unittest.TestCase):
    def test_public_host_does_not_seed_demo(self):
        self.assertFalse(ACC.demo_allowed("0.0.0.0"))
        self.assertTrue(ACC.demo_allowed("127.0.0.1"))

    def test_env_can_disable_demo(self):
        with mock.patch.dict("os.environ", {"GROUNDED_DEMO": "0"}):
            self.assertFalse(ACC.demo_allowed("127.0.0.1"))


class TaskShapeCase(unittest.TestCase):
    def test_drops_task_without_done_when(self):
        t = {"id": "T-x", "priority": "P0", "title": "随便", "why": "因为",
             "action": "做", "acceptance": {}, "status": "todo"}
        self.assertIsNone(P.customer_task(t))

    def test_five_fields_and_human_copy(self):
        t = {
            "id": "T-005", "priority": "P0", "status": "todo",
            "title": "修复前端渲染空壳页（SSR / 预渲染）",
            "why": "静态 HTML 无正文，多数 AI 抓取器看到的是空白页",
            "action": "对受影响路由启用 SSR 或预渲染",
            "acceptance": {"type": "auto", "desc": "受影响页面重抓后正文词数 ≥ 120"},
        }
        c = P.customer_task(t)
        self.assertEqual(c["band"], "先做")
        self.assertEqual(c["status_label"], "未开始")
        self.assertNotIn("SSR", c["do"])
        self.assertTrue(c["done_when"])

    def test_regressed_after_failed_recheck(self):
        t = {"id": "T-1", "priority": "P1", "status": "todo",
             "action": "改", "why": "因为", "closed_at": "2026-08-25",
             "acceptance": {"type": "auto", "desc": "达标"},
             "evidence": [{"result": "fail"}]}
        self.assertEqual(P.customer_task(t)["status_label"], "退步了")

    def test_regressed_marker_survives_closed_at_clear(self):
        t = {"id": "T-1", "priority": "P1", "status": "todo",
             "action": "改", "why": "因为", "closed_at": None,
             "regressed_at": "2026-08-28",
             "acceptance": {"type": "auto", "desc": "达标"},
             "evidence": [{"result": "fail"}]}
        self.assertEqual(P.customer_task(t)["status_label"], "退步了")


class JourneyCase(unittest.TestCase):
    def test_journey_stays_on_detection_without_samples(self):
        with mock.patch.object(P, "action_plan", return_value=[]):
            j = P.journey("x", sampled=False)
        self.assertEqual(j["current"], "detect")
        self.assertEqual(j["primary"]["action"], "detect")

    def test_journey_focuses_only_three_open_tasks(self):
        items = [{"id": str(i), "status": "todo"} for i in range(6)]
        with mock.patch.object(P, "action_plan", return_value=items):
            j = P.journey("x", sampled=True)
        self.assertEqual(j["current"], "act")
        self.assertEqual(len(j["focus"]), 3)

    def test_verify_job_progress_uses_human_copy(self):
        job = {"id": "j", "action": "verify", "status": "running"}
        with mock.patch.object(SV.J, "tail",
                               return_value=("=== 重抓站点 ===\n=== 重跑体检 ===", 20)):
            p = SV._job_progress(job)
        self.assertEqual(p["percent"], 52)
        self.assertNotIn("体检", p["label"])


class BrandFactsCase(unittest.TestCase):
    def test_definition_save_creates_customer_fact_source(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(G, "WORK", Path(td)):
            SV._save_definition(
                "brand", {"name": "Brand", "site": "https://brand.test",
                          "aliases": ["B"]}, "Brand 是一款测试产品。")
            text = (Path(td) / "brand" / "content" / "facts.md").read_text("utf-8")
        self.assertIn("## 一句话定义", text)
        self.assertIn("Brand 是一款测试产品。", text)


@unittest.skipUnless(
    (HERE.parent / "geolook" / "work" / "wagnab" / "tasks.json").exists(),
    "no wagnab project")
class WagnabPresentCase(unittest.TestCase):
    def test_every_plan_item_has_done_when(self):
        items = P.action_plan("wagnab")
        self.assertTrue(items)
        for t in items:
            self.assertTrue(t["done_when"], t["id"])
            self.assertNotIn("SSR", t["do"] + t["why"])

    def test_overview_does_not_fake_zero_health_without_samples(self):
        ov = P.overview("wagnab")
        self.assertEqual(ov["conclusion"]["kind"], "empty")
        self.assertEqual(ov["health"]["state"], "unmeasured")
        self.assertEqual(ov["health"]["label"], "还没测")
        self.assertEqual(ov["mention"]["state"], "unmeasured")
        self.assertNotEqual(ov["mention"]["label"], "0%")
        self.assertFalse(ov["engines"])
        self.assertIsNone(ov["plugin"])
        self.assertTrue(ov["next3"])
        self.assertEqual(len(ov["next3"]), 3)

    def test_effect_hides_baseline_verify(self):
        self.assertTrue(P.effect("wagnab")["empty"])

