import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import deliver as DL
import report as R


class TestServePipelineOrder(unittest.TestCase):
    """serve 必须在打包之前跑 deliverables。

    回归自实跑：serve 从「验收」直接跳到「打包交付」，而 deliver 的
    02-执行方案 取的是 deliverables 产出的 plan.md——漏了这一步，
    交付包会静默缺 02 号，客户拿到的包不完整且没有任何报错。
    """

    def setUp(self):
        self.src = (Path(__file__).parent.parent / "scripts" / "geo.py").read_text("utf-8")
        start = self.src.index("def cmd_serve(")
        self.body = self.src[start:self.src.index("\ndef ", start + 10)]

    def test_deliverables_runs_in_serve(self):
        self.assertIn("DV.run(", self.body, "serve 未调用 deliverables")

    def test_deliverables_runs_before_deliver(self):
        self.assertLess(self.body.index("DV.run("), self.body.index("deliver.run("),
                        "deliverables 必须在 deliver 之前——后者依赖前者产出的 plan.md")

    def test_deliver_reads_execution_plan_from_deliverables(self):
        """02-执行方案 的源必须是真实存在的文件。

        回归自实跑：deliver 原先找 pdir/"plan.md"，而没有任何代码产出它——
        条件永远为假，02 号从来没进过交付包，可 README 和模块说明都写着「包里有 02」。
        """
        src = (Path(__file__).parent.parent / "scripts" / "deliver.py").read_text("utf-8")
        self.assertNotIn('pdir / "plan.md"', src, "不该再依赖不存在的 plan.md")
        self.assertIn("3-GEO执行方案", src, "应取自 deliverables 的第三份文档")

    def test_step_labels_match_actual_step_count(self):
        labels = re.findall(r"═══ (\d+)/(\d+) ", self.body)
        self.assertTrue(labels, "未找到步骤标签")
        totals = {t for _, t in labels}
        self.assertEqual(len(totals), 1, f"步骤总数不一致：{totals}")
        nums = sorted(int(n) for n, _ in labels)
        self.assertEqual(nums, list(range(1, int(totals.pop()) + 1)),
                         "步骤编号应连续且与总数吻合")


def _task(tid="T-001"):
    return {"id": tid, "priority": "P0", "package": "技术底座", "market": "cn",
            "title": "修标题", "why": "w", "action": "a", "owner": "开发",
            "effort": "S", "window": "30 天", "status": "todo",
            "acceptance": {"type": "auto", "desc": "d"}, "affected": []}


TASKS = {"tasks": [_task()],
         "summary": {"total": 1, "auto_verifiable": 1,
                     "by_priority": {"P0": 1, "P1": 0, "P2": 0},
                     "by_status": {"todo": 1}}}


def _project(d, slug="x", audit_date=None, verify_date=None, report_dirs=()):
    """建最小可用项目：audit/tasks 必备，verify/reports 按参数给。"""
    pdir = Path(d) / slug
    pdir.mkdir(parents=True)
    (pdir / "geo.json").write_text(json.dumps(
        {"brand": {"name": "X", "site": "https://x.com"}, "market": "cn"},
        ensure_ascii=False), "utf-8")
    G.write_json(pdir / "audit.json",
                 {"audited_at": f"{audit_date or G.today()}T10:00:00",
                  "page_count": 3, "avg_score": 60})
    G.write_json(pdir / "tasks.json", TASKS)
    if verify_date:
        (pdir / "verify").mkdir()
        G.write_json(pdir / "verify" / f"{verify_date}.json",
                     {"verified_at": f"{verify_date}T09:00:00", "audit_avg_score": 60,
                      "changed": 0,
                      "results": [{"id": "T-001", "title": "修标题", "priority": "P0",
                                   "verdict": "通过", "note": "ok"}]})
    for rd in report_dirs:
        rdir = pdir / "reports" / rd
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "report.md").write_text(f"# 报告 {rd}", "utf-8")
    return pdir


class TestRebuild(unittest.TestCase):
    def test_stale_files_removed_on_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d)
            out = Path(d) / "x" / "delivery" / G.today()
            out.mkdir(parents=True)
            (out / "04-验收表.html").write_text("旧", "utf-8")  # 上次条件生成的残留
            (out / "假文件.txt").write_text("旧", "utf-8")
            with mock.patch.object(G, "WORK", Path(d)):
                DL.run("x")
            self.assertFalse((out / "假文件.txt").exists())


class TestUnverified(unittest.TestCase):
    def test_no_verify_marked_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d)
            with mock.patch.object(G, "WORK", Path(d)):
                out = DL.run("x")
            vmd = (out / "04-验收表.md").read_text("utf-8")
            self.assertIn("本期未验收", vmd)
            self.assertIn("尚无验收记录", vmd)
            self.assertIn("本期未验收", (out / "README.md").read_text("utf-8"))

    def test_verify_older_than_audit_marked_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d, audit_date="2026-07-28", verify_date="2026-07-27")
            with mock.patch.object(G, "WORK", Path(d)):
                out = DL.run("x")
            vmd = (out / "04-验收表.md").read_text("utf-8")
            self.assertIn("本期未验收", vmd)
            self.assertIn("2026-07-27", vmd)
            self.assertNotIn("| 编号 | 任务 |", vmd)  # 不静默复用旧验收结果

    def test_verify_same_day_used(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d, verify_date=G.today())
            with mock.patch.object(G, "WORK", Path(d)):
                out = DL.run("x")
            vmd = (out / "04-验收表.md").read_text("utf-8")
            self.assertIn("| 编号 | 任务 |", vmd)
            self.assertNotIn("本期未验收", vmd)


class TestReportDateConsistency(unittest.TestCase):
    def test_mismatch_triggers_report_rerun(self):
        # 今天有体检但最新报告是昨天的：先补跑报告
        with tempfile.TemporaryDirectory() as d:
            _project(d, report_dirs=["2026-07-27"])

            def fake_run(slug):
                rdir = Path(d) / slug / "reports" / G.today()
                rdir.mkdir(parents=True)
                (rdir / "report.md").write_text("# 今日报告", "utf-8")

            with mock.patch.object(G, "WORK", Path(d)), \
                    mock.patch.object(R, "run", side_effect=fake_run) as m:
                out = DL.run("x")
            m.assert_called_once_with("x")
            self.assertEqual((out / "01-诊断报告.md").read_text("utf-8"), "# 今日报告")
            self.assertNotIn("诊断报告日期", (out / "README.md").read_text("utf-8"))

    def test_mismatch_noted_when_rerun_fails(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d, audit_date="2026-07-28", report_dirs=["2026-07-26"])
            with mock.patch.object(G, "WORK", Path(d)), \
                    mock.patch.object(R, "run", side_effect=RuntimeError("boom")):
                out = DL.run("x")
            readme = (out / "README.md").read_text("utf-8")
            self.assertIn("诊断报告日期 2026-07-26", readme)
            self.assertIn("本期体检日期 2026-07-28", readme)


if __name__ == "__main__":
    unittest.main()
