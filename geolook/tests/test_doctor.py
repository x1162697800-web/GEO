import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import doctor as D
import geolib as G


def _levels(rows, item_substr):
    return [lvl for lvl, item, _, _ in rows if item_substr in item]


class TestEnvChecks(unittest.TestCase):
    """.env 的静默失效是交付时最难查的一类，doctor 必须逐条挑明。"""

    def _run_env_check(self, raw: bytes | None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            if raw is not None:
                (root / ".env").write_bytes(raw)
            with mock.patch.object(G, "ROOT", root):
                r = D.Report()
                D._check_env_file(r)
                return r.rows

    def test_missing_env_warns_not_fails(self):
        """没有引擎不是阻塞——抓取/体检/工单/资产都不需要它。"""
        rows = self._run_env_check(None)
        self.assertEqual(_levels(rows, ".env 不存在"), [D.WARN])

    def test_bom_is_flagged(self):
        """BOM 是实跑撞到的坑：key 看着配了却读不到。"""
        rows = self._run_env_check("\ufeffDEEPSEEK_API_KEY=sk-a\n".encode("utf-8"))
        self.assertEqual(_levels(rows, "BOM"), [D.WARN])

    def test_clean_env_passes_encoding(self):
        rows = self._run_env_check(b"DEEPSEEK_API_KEY=sk-a\n")
        self.assertEqual(_levels(rows, ".env 编码"), [D.OK])
        self.assertFalse(_levels(rows, "BOM"))

    def test_unclosed_quote_flagged(self):
        rows = self._run_env_check(b'DEEPSEEK_API_KEY="sk-a\n')
        self.assertEqual(_levels(rows, "引号不闭合"), [D.WARN])

    def test_lowercase_key_name_flagged(self):
        rows = self._run_env_check(b"deepseek_api_key=sk-a\n")
        self.assertEqual(_levels(rows, "键名可疑"), [D.WARN])

    @unittest.skipIf(os.name == "nt", "POSIX 专属：Windows 上 chmod 不表达权限位")
    def test_wide_permissions_fail_on_posix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / ".env"
            p.write_bytes(b"DEEPSEEK_API_KEY=sk-a\n")
            p.chmod(0o644)
            with mock.patch.object(G, "ROOT", root):
                r = D.Report()
                D._check_env_file(r)
            self.assertEqual(_levels(r.rows, "权限过宽"), [D.FAIL])

    @unittest.skipUnless(os.name == "nt", "Windows 专属：必须明说保护不生效")
    def test_windows_permission_caveat_surfaced(self):
        rows = self._run_env_check(b"DEEPSEEK_API_KEY=sk-a\n")
        self.assertEqual(_levels(rows, ".env 权限"), [D.WARN])


class TestEngineChecks(unittest.TestCase):
    def _run(self, env: dict):
        with mock.patch.dict(os.environ, env, clear=True):
            r = D.Report()
            D._check_engines(r)
            return r.rows

    def test_no_engine_warns(self):
        rows = self._run({})
        self.assertEqual(_levels(rows, "引擎接入"), [D.WARN])

    def test_non_search_engine_flags_evidence_quality(self):
        """全是不联网引擎时要提醒：测的是参数化知识，不是引用级证据。"""
        rows = self._run({"DEEPSEEK_API_KEY": "sk-a"})
        self.assertEqual(_levels(rows, "引擎接入"), [D.OK])
        self.assertEqual(_levels(rows, "无原生联网"), [D.WARN])

    def test_search_engine_clears_the_flag(self):
        rows = self._run({"PERPLEXITY_API_KEY": "pplx-a"})
        self.assertFalse(_levels(rows, "无原生联网"))

    def test_single_market_flagged(self):
        rows = self._run({"DEEPSEEK_API_KEY": "sk-a"})
        self.assertEqual(_levels(rows, "海外市场无可用引擎"), [D.WARN])
        self.assertFalse(_levels(rows, "国内市场无可用引擎"))


class TestReportSemantics(unittest.TestCase):
    def test_exit_code_only_blocks_on_fail(self):
        r = D.Report()
        r.add(D.WARN, "x")
        self.assertEqual(r.failed, 0)
        r.add(D.FAIL, "y")
        self.assertEqual(r.failed, 1)

    def test_deps_present(self):
        r = D.Report()
        D._check_deps(r)
        self.assertEqual([lvl for lvl, *_ in r.rows], [D.OK] * 3)


if __name__ == "__main__":
    unittest.main()
