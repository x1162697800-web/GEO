import os
import socket
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import dashboard as D


class TestAuthOk(unittest.TestCase):
    TOKEN = "s3cret-token"

    def test_no_token_configured_allows_all(self):
        self.assertTrue(D.auth_ok(None, None))
        self.assertTrue(D.auth_ok("", "anything=1"))

    def test_query_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, None, query_token=self.TOKEN))

    def test_header_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, None, header_token=self.TOKEN))

    def test_cookie_digest_matches(self):
        cookie = f"other=1; {D.AUTH_COOKIE}={D._token_digest(self.TOKEN)}"
        self.assertTrue(D.auth_ok(self.TOKEN, cookie))

    def test_wrong_credentials_rejected(self):
        self.assertFalse(D.auth_ok(self.TOKEN, None))
        self.assertFalse(D.auth_ok(self.TOKEN, None, query_token="wrong"))
        self.assertFalse(D.auth_ok(self.TOKEN, f"{D.AUTH_COOKIE}=deadbeef"))
        # cookie 里放原始令牌不行——cookie 存的是摘要
        self.assertFalse(D.auth_ok(self.TOKEN, f"{D.AUTH_COOKIE}={self.TOKEN}"))


class TestPublicBindGuard(unittest.TestCase):
    def test_public_host_without_token_dies(self):
        with mock.patch.dict(D.os.environ, {}, clear=True), \
             self.assertRaises(SystemExit):
            D.run(port=0, open_browser=False, host="0.0.0.0", token=None)


class TestPortGuard(unittest.TestCase):
    """端口被占时必须拒绝启动。

    Windows 的 SO_REUSEADDR 允许绑上一个正在监听的端口，默认配置下看板会
    「启动成功」却把请求让给别人的服务——首页 200、所有 /api/* 404，
    症状极难排查。所以要主动探测并拒绝。
    """

    def test_reports_taken_port(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(D._port_taken("127.0.0.1", port))
        finally:
            srv.close()
        # 关掉之后应当立刻判为可用
        self.assertFalse(D._port_taken("127.0.0.1", port))

    def test_run_dies_when_port_taken(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            with mock.patch.dict(D.os.environ, {}, clear=True), \
                 self.assertRaises(SystemExit):
                D.run(port=port, open_browser=False, host="127.0.0.1")
        finally:
            srv.close()

    @unittest.skipUnless(os.name == "nt", "只有 Windows 的 SO_REUSEADDR 会劫持监听中的端口")
    def test_no_address_reuse_on_windows(self):
        self.assertFalse(D._Server.allow_reuse_address)

    @unittest.skipIf(os.name == "nt", "POSIX 需要复用 TIME_WAIT，否则重启会失败")
    def test_address_reuse_kept_on_posix(self):
        self.assertTrue(D._Server.allow_reuse_address)


if __name__ == "__main__":
    unittest.main()
