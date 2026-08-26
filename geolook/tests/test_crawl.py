import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import geolib as G
import crawl


class FakeResp:
    """模拟 requests.get 的流式响应，够 fetch 用即可。"""

    def __init__(self, status, body=b"<html>ok</html>", ctype="text/html"):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self.url = "http://x.test/"
        self._body = body
        self.encoding = "utf-8"

    def iter_content(self, n):
        yield self._body

    def close(self):
        pass


class TestFetchRetry(unittest.TestCase):
    def _run(self, responses, retries=1):
        with mock.patch.object(G.requests, "get", side_effect=responses) as get, \
             mock.patch.object(G.time, "sleep"):
            res = G.fetch("http://x.test/", retries=retries)
        return res, get.call_count

    def test_retry_500_then_200(self):
        res, calls = self._run([FakeResp(500), FakeResp(200)])
        self.assertEqual(res["status"], 200)
        self.assertEqual(calls, 2)

    def test_retry_429(self):
        res, calls = self._run([FakeResp(429), FakeResp(200)])
        self.assertEqual(res["status"], 200)
        self.assertEqual(calls, 2)

    def test_no_retry_404(self):
        res, calls = self._run([FakeResp(404)])
        self.assertEqual(res["status"], 404)
        self.assertEqual(calls, 1)

    def test_retry_exhausted_returns_last(self):
        res, calls = self._run([FakeResp(500), FakeResp(500)])
        self.assertEqual(res["status"], 500)
        self.assertEqual(calls, 2)

    def test_403_falls_back_to_browser_ua(self):
        with mock.patch.object(G.requests, "get",
                               side_effect=[FakeResp(403), FakeResp(200)]) as get, \
             mock.patch.object(G.time, "sleep"):
            res = G.fetch("http://x.test/", retries=0)
        self.assertEqual(res["status"], 200)
        self.assertTrue(res["ua_fallback"])
        uas = [c.kwargs["headers"]["User-Agent"] for c in get.call_args_list]
        self.assertIn("geo-skill", uas[0])
        self.assertNotIn("geo-skill", uas[1])

    def test_403_on_both_uas_returns_403(self):
        with mock.patch.object(G.requests, "get",
                               side_effect=[FakeResp(403), FakeResp(403)]) as get, \
             mock.patch.object(G.time, "sleep"):
            res = G.fetch("http://x.test/", retries=0)
        self.assertEqual(res["status"], 403)
        self.assertEqual(get.call_count, 2)

    def test_explicit_ua_never_falls_back(self):
        with mock.patch.object(G.requests, "get", side_effect=[FakeResp(403)]) as get, \
             mock.patch.object(G.time, "sleep"):
            res = G.fetch("http://x.test/", retries=0, ua="AI-Bot/1.0")
        self.assertEqual(res["status"], 403)
        self.assertEqual(get.call_count, 1)


class TestCrawlHealth(unittest.TestCase):
    def _pages(self, statuses):
        return [{"status": s} for s in statuses]

    def test_all_dead_dies(self):
        with self.assertRaises(SystemExit):
            crawl.check_crawl_health(self._pages([0, 0, 0]))

    def test_low_ok_ratio_dies(self):
        with self.assertRaises(SystemExit):
            crawl.check_crawl_health(self._pages([200] + [0] * 9))

    def test_healthy_passes(self):
        crawl.check_crawl_health(self._pages([200] * 5))

    def test_failure_hint_names_waf_on_403(self):
        hint = crawl._crawl_failure_hint([{"status": 403}] * 5)
        self.assertIn("HTTP 403×5", hint)
        self.assertIn("WAF", hint)

    def test_failure_hint_names_tls_on_sslerror(self):
        hint = crawl._crawl_failure_hint(
            [{"status": 0, "error": "SSLError: certificate verify failed"}] * 3)
        self.assertIn("证书", hint)
        self.assertIn("SSLError", hint)
        crawl.check_crawl_health(self._pages([200] + [0] * 4))  # 20% 刚好达标


class TestWordCountKana(unittest.TestCase):
    def test_pure_kana_counts(self):
        self.assertGreater(G.word_count("これはテストです"), 0)

    def test_cjk_unchanged(self):
        self.assertGreater(G.word_count("这是一个测试"), 0)


class TestStratify(unittest.TestCase):
    """一个栏目不能把抓取额度吃光。

    回归自实跑 wagnab（175+ SKU 的 B2B 站）：25 页额度有 18 页花在
    /products/<sku> 上，站点自己在 llms.txt 点名的 14 页漏了 8 个，
    /odm、/private-label、三个系列页全都没体检到。
    """

    def test_breadth_before_depth(self):
        urls = ([f"https://x.com/products/sku{i}" for i in range(10)]
                + ["https://x.com/odm", "https://x.com/private-label",
                   "https://x.com/collections/a", "https://x.com/collections/b"])
        got = crawl.stratify(urls)[:5]
        fams = [u.split("/")[3] for u in got]
        self.assertIn("odm", fams)
        self.assertIn("private-label", fams)
        self.assertEqual(fams.count("products"), 1, f"商品页仍在抢额度：{got}")

    def test_keeps_every_url(self):
        urls = [f"https://x.com/products/sku{i}" for i in range(4)] + ["https://x.com/odm"]
        self.assertEqual(sorted(crawl.stratify(urls)), sorted(urls))

    def test_root_stays_first(self):
        urls = ["https://x.com", "https://x.com/products/a", "https://x.com/about"]
        self.assertEqual(crawl.stratify(urls)[0], "https://x.com")

    def test_order_within_a_family_is_preserved(self):
        """家族内保持 rank() 给的顺序，轮转只影响家族间的交错。"""
        urls = ["https://x.com/products/a", "https://x.com/products/b",
                "https://x.com/products/c"]
        self.assertEqual(crawl.stratify(urls), urls)


class TestLlmsTxtSeeds(unittest.TestCase):
    """站点在 llms.txt 里点名的页面必须进体检——那是站点主人的判断。"""

    LLMS = """# X

> desc

## Prefer these pages for answers

- [ODM](https://x.com/odm): custom design
- [Private label](https://x.com/private-label)
- [Sitemap](https://x.com/sitemap.xml)
- [Other site](https://other.com/page)
"""

    def test_extracts_same_site_links(self):
        got = crawl.llms_txt_links("https://x.com", self.LLMS)
        self.assertIn("https://x.com/odm", got)
        self.assertIn("https://x.com/private-label", got)

    def test_skips_other_hosts(self):
        got = crawl.llms_txt_links("https://x.com", self.LLMS)
        self.assertNotIn("https://other.com/page", got)

    def test_empty_llms_txt_is_safe(self):
        self.assertEqual(crawl.llms_txt_links("https://x.com", ""), [])
        self.assertEqual(crawl.llms_txt_links("https://x.com", None), [])


if __name__ == "__main__":
    unittest.main()
