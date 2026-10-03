"""The gateway serves the plaza without the dashboard login, and nothing else."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[3] / "legacy" / "dashboard" / "server.py"


def load():
    env = Path(tempfile.mkdtemp()) / "env"                # never the real keys: the tests bring their own login
    env.write_text("DASHBOARD_USER=tester\nDASHBOARD_PASSWORD=not-a-real-one\nGATEWAY_TOKEN=bot-token-for-tests\n")
    os.environ["DASHBOARD_ENV_FILE"] = str(env)
    for k in ("DASHBOARD_USER", "DASHBOARD_PASSWORD", "GATEWAY_TOKEN", "GATEWAY_TOKENS"):
        os.environ.pop(k, None)
    spec = importlib.util.spec_from_file_location("legacy_gateway_for_plaza_test", GATEWAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(GATEWAY.exists(), "no gateway in this checkout")
class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load()
        cls.g.PLAZA_URL = "http://127.0.0.1:9"            # nothing listens: a whitelisted route answers 502, not 401
        cls.srv = cls.g.Server(("127.0.0.1", 0), cls.g.Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def status(self, method, path, **headers):
        req = urllib.request.Request(self.base + path, data=b"{}" if method in ("POST", "PUT") else None, method=method,
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def test_whitelist(self):
        g = self.g
        for path in ("/plaza", "/plaza/", "/plaza/agents.md", "/plaza/cards.json", "/plaza/static/plaza.css",
                     "/plaza/static/plaza.js", "/plaza/api/teams", "/plaza/api/team/t04", "/plaza/api/matches",
                     "/plaza/api/wall", "/plaza/api/health"):
            self.assertTrue(g.is_plaza(path), path)
        for path in ("/plaza/team/t02", "/plaza/card/SAL-09", "/plaza/floor", "/plaza/market", "/plaza/api/offers",
                     "/plaza/api/floor", "/plaza/api/floor/stream", "/plaza/api/card/SAL-09", "/plaza/static/components.js"):
            self.assertTrue(g.is_plaza(path), path)
        for path in ("/plaza/admin", "/plaza/admin/", "/plaza/admin/api/overview", "/plaza/admin/static/admin.js",
                     "/plaza/api/admin", "/plaza/team/t2", "/plaza/card/sal-09"):
            self.assertFalse(g.is_plaza(path), path)
        self.assertTrue(g.is_plaza("/plaza/api/floor", "POST"))
        self.assertFalse(g.is_plaza("/plaza/admin/api/action", "POST"))
        self.assertTrue(g.is_plaza_admin("/plaza/admin/api/action", "POST"))
        self.assertFalse(g.is_plaza_admin("/plaza/admin/api/action", "PUT"))
        self.assertFalse(g.is_plaza_admin("/plaza/admin/api/../../x"))
        self.assertTrue(g.PLAZA_QUERY.fullmatch("set=SAL&rarity=rare&side=ask"))
        for path in ("/plaza/static/../../.env", "/plaza/api/team/t4", "/plaza/api/control", "/plaza/x", "/plazax",
                     "/plaza/static/app.js", "/v2/plaza/", "/plaza/api/team/t04/x", "/plaza//", "/plaza/api/claim/"):
            self.assertFalse(g.is_plaza(path), path)
        self.assertTrue(g.is_plaza("/plaza/api/claim", "POST"))
        self.assertTrue(g.is_plaza("/plaza/api/team/t04", "PUT"))
        for method, path in (("POST", "/plaza/api/team/t04"), ("PUT", "/plaza/api/claim"), ("DELETE", "/plaza/api/team/t04"),
                             ("POST", "/plaza/api/teams"), ("PATCH", "/plaza/api/team/t04")):
            self.assertFalse(g.is_plaza(path, method), (method, path))
        self.assertTrue(g.PLAZA_QUERY.fullmatch("team=t04"))
        for path in ("/plaza/connect", "/plaza/me", "/plaza/match/m-0123456789", "/plaza/art/LAT-06.svg",
                     "/plaza/api/connect/status", "/plaza/api/me", "/plaza/api/match/m-0123456789"):
            self.assertTrue(g.is_plaza(path), path)
        for path in ("/plaza/api/connect/start", "/plaza/api/connect/agent", "/plaza/api/match/m-0123456789/message"):
            self.assertTrue(g.is_plaza(path, "POST"), path)
            self.assertFalse(g.is_plaza(path), path)
        for path in ("/plaza/art/LAT-06.svg/x", "/plaza/art/../x.svg", "/plaza/api/match/m-1", "/plaza/api/connect/x",
                     "/plaza/api/match/m-0123456789/thread"):
            self.assertFalse(g.is_plaza(path), path)
        self.assertTrue(g.PLAZA_QUERY.fullmatch("session=" + "aB3_-" * 6))
        self.assertTrue(g.is_plaza_admin("/plaza/admin/api/matchmaker"))
        self.assertFalse(g.is_plaza("/plaza/admin/api/matchmaker"))
        self.assertEqual(g.PLAZA_COOKIE.search("a=1; plaza_session=" + "x" * 32 + "; other=secret").group(1),
                         "plaza_session=" + "x" * 32)
        self.assertIsNone(g.PLAZA_COOKIE.search("dashboard=secret; plaza_session=short"))
        self.assertFalse(g.PLAZA_QUERY.fullmatch("team=t04&x=../"))

    def test_private_routes_still_need_the_login(self):
        for path in ("/v2/", "/v2/control", "/v2/brain/chat", "/api/me", "/bot/status", "/plaza/api/control",
                     "/plaza/static/../../.env", "/gateway/whoami"):
            self.assertEqual(self.status("GET", path), 401, path)
        for method, path in (("POST", "/v2/control"), ("POST", "/api/offers"), ("PUT", "/plaza/api/claim"),
                             ("DELETE", "/plaza/api/team/t04"), ("POST", "/plaza/api/teams")):
            self.assertEqual(self.status(method, path), 401, (method, path))

    def test_admin_needs_the_dashboard_login(self):
        for path in ("/plaza/admin/", "/plaza/admin/api/overview", "/plaza/admin/api/activity", "/plaza/admin/static/admin.js",
                     "/plaza/admin/api/matchmaker"):
            self.assertEqual(self.status("GET", path), 401, path)
        self.assertEqual(self.status("POST", "/plaza/admin/api/action"), 401)
        if self.g.GATEWAY_TOKENS:                             # a bot token is not a dashboard login
            token = next(iter(self.g.GATEWAY_TOKENS))
            self.assertEqual(self.status("GET", "/plaza/admin/api/overview", **{"X-Team-Key": token}), 403)
        if self.g.DASHBOARD_AUTH != ":":
            import base64
            basic = {"Authorization": "Basic " + base64.b64encode(self.g.DASHBOARD_AUTH.encode()).decode()}
            self.assertEqual(self.status("GET", "/plaza/admin/api/overview", **basic), 502)       # forwarded
            self.assertEqual(self.status("POST", "/plaza/admin/api/action", **basic), 403)        # no X-Dashboard header
            self.assertEqual(self.status("POST", "/plaza/admin/api/action", **basic, **{"X-Dashboard": "1"}), 502)

    def test_gateway_refuses_to_start_without_the_login(self):
        g = self.g
        g.require_login({"DASHBOARD_USER": "a", "DASHBOARD_PASSWORD": "b"})
        for env in ({}, {"DASHBOARD_USER": "a"}, {"DASHBOARD_USER": " ", "DASHBOARD_PASSWORD": "b"}):
            with self.assertRaises(SystemExit) as e:
                g.require_login(env)
            self.assertIn("NOT started", str(e.exception))
        empty = Path(tempfile.mkdtemp()) / "empty.env"
        empty.write_text("")
        run = subprocess.run([sys.executable, str(GATEWAY)], capture_output=True, text=True, timeout=30,
                             env={"PATH": os.environ.get("PATH", ""), "DASHBOARD_ENV_FILE": str(empty),
                                  "DASHBOARD_PORT": "1"})
        self.assertNotEqual(run.returncode, 0)                 # loud, and before it listens anywhere
        self.assertIn("DASHBOARD_USER and DASHBOARD_PASSWORD empty", run.stderr)
        self.assertIn("DASHBOARD_ENV_FILE=.env", run.stderr)

    def test_plaza_routes_pass_without_login(self):
        self.assertEqual(self.status("POST", "/plaza/api/connect/start"), 502)
        self.assertEqual(self.status("GET", "/plaza/api/connect/status"), 502)
        self.assertEqual(self.status("GET", "/plaza/api/floor/stream"), 502)
        self.assertEqual(self.status("POST", "/plaza/api/floor"), 502)
        self.assertEqual(self.status("GET", "/plaza/api/health"), 502)      # forwarded: the upstream is down here
        self.assertEqual(self.status("POST", "/plaza/api/claim"), 502)
        self.assertEqual(self.status("PUT", "/plaza/api/team/t04"), 502)


if __name__ == "__main__":
    unittest.main()
