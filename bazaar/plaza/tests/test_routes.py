"""One list of routes: the server answers every live one, the gateway forwards every one, the page finds its files."""
import json
import re
import unittest
from pathlib import Path

from bazaar.plaza import routes
from bazaar.plaza.tests import test_gateway
from bazaar.plaza.tests.test_server import ServerTest

WEB = Path(routes.__file__).parent / "web"
PARAMS = {"{team}": "t09", "{ref}": "LAT-06", "{match}": "m-0123456789", "{lot}": "l-01234567"}
ADMIN = {"X-Plaza-Admin": "test-admin-token"}


def concrete(path: str) -> str:
    for k, v in PARAMS.items():
        path = path.replace(k, v)
    return "/plaza" + path


class RouteListTest(unittest.TestCase):
    def test_rows_are_well_formed(self):
        seen = set()
        for r in routes.ROUTES:
            self.assertIn(r.method, ("GET", "POST", "PUT"), r)
            self.assertIn(r.who, ("anyone", "team", "agent", "session", "admin"), r)
            self.assertTrue(r.path.startswith("/api/") or r.path.startswith("/admin/api/"), r)
            self.assertEqual(r.who == "admin", r.path.startswith("/admin/"), r)
            self.assertNotIn((r.method, r.path), seen, r)
            seen.add((r.method, r.path))
            self.assertTrue(r.what and r.what[0].isupper(), r)
            if r.method != "GET":
                self.assertIsInstance(r.body, dict, r)

    def test_every_fixture_exists_and_parses(self):
        for r in routes.ROUTES:
            if r.fixture:
                json.loads((WEB / "fixtures" / r.fixture).read_text(encoding="utf-8"))

    def test_openapi_lists_the_live_routes_only(self):
        doc = routes.openapi("X")
        live = {("/plaza" + r.path, r.method.lower()) for r in routes.ROUTES if r.live and r.who != "admin"}
        self.assertEqual({(p, m) for p, ops in doc["paths"].items() for m in ops}, live)
        self.assertFalse(any("/admin/" in p for p in doc["paths"]))                  # the public list never names the panel
        everything = routes.openapi("X", admin=True)
        self.assertEqual(len([m for ops in everything["paths"].values() for m in ops]), len([r for r in routes.ROUTES if r.live]))
        self.assertTrue(all("x-screen" in op for ops in everything["paths"].values() for op in ops.values()))

    @unittest.skipUnless(test_gateway.GATEWAY.exists(), "no gateway in this checkout")
    def test_the_gateway_forwards_every_route(self):
        g = test_gateway.load()
        for r in routes.ROUTES:
            path = concrete(r.path)
            check = g.is_plaza_admin if r.who == "admin" else g.is_plaza
            self.assertTrue(check(path, r.method), f"{r.method} {path}")
            if r.who == "admin":
                self.assertFalse(g.is_plaza(path, r.method), path)       # never without the dashboard login

    def test_the_page_finds_every_file_it_loads(self):
        for page in ("index.html", "admin.html"):
            html = (WEB / page).read_text(encoding="utf-8")
            for url in re.findall(r'(?:src|href)="(/plaza/[^"]+)"', html):
                m = re.fullmatch(r"/plaza/static/(.+)", url)
                a = re.fullmatch(r"/plaza/admin/static/screens/(.+)", url)
                if m:
                    self.assertTrue((WEB / m.group(1)).is_file(), url)
                elif a:
                    self.assertTrue((WEB / "admin" / a.group(1)).is_file(), url)
                else:
                    self.assertEqual(url, "/plaza/admin/static/admin.js", url)


class LiveRoutesTest(unittest.TestCase):
    setUp, tearDown, call = ServerTest.setUp, ServerTest.tearDown, ServerTest.call

    def test_every_live_route_answers(self):
        for r in routes.ROUTES:
            if not r.live or r.path == "/api/floor/stream":
                continue
            st, body, _ = self.call(r.method, concrete(r.path), r.body if r.method != "GET" else None,
                                    ADMIN if r.who == "admin" else None)
            missing = st == 404 and isinstance(body, dict) and body.get("message") in ("no such endpoint", "no such page")
            self.assertFalse(missing, f"{r.method} {r.path} is in the list but the server has no such route")
            self.assertLess(st, 500, f"{r.method} {r.path} answered {st}")

    def test_openapi_and_the_documents_are_served(self):
        st, doc, _ = self.call("GET", "/plaza/api/openapi.json")
        self.assertEqual(st, 200)
        self.assertIn("/plaza/api/health", doc["paths"])
        for path in ("/plaza/AGENTS.md", "/AGENTS.md", "/plaza/agents.md"):
            self.assertEqual(self.call("GET", path)[0], 200, path)

    def test_pages_and_static_files(self):
        for path in ("/plaza/", "/plaza/home", "/plaza/cards", "/plaza/offers", "/plaza/offers/m-0123456789", "/plaza/activity",
                     "/plaza/market", "/plaza/card/LAT-06", "/plaza/settings", "/plaza/suggest", "/plaza/docs", "/plaza/how",
                     "/plaza/connect", "/plaza/agents", "/plaza/_kit"):
            st, html, _ = self.call("GET", path)
            self.assertEqual(st, 200, path)
            self.assertIn("/plaza/static/plaza.js", html)
        for path in ("/plaza/static/api.js", "/plaza/static/i18n.js", "/plaza/static/screens/kit.js", "/plaza/static/i18n/shell.js",
                     "/plaza/static/fixtures/status.json", "/plaza/static/fixtures/admin/overview.json"):
            self.assertEqual(self.call("GET", path)[0], 200, path)
        for path in ("/plaza/static/screens/../server.py", "/plaza/static/fixtures/../../store.py", "/plaza/static/screens/x.py",
                     "/plaza/static/admin/overview.js", "/plaza/static/Screens/kit.js"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_the_panel_is_ours_only(self):
        for path in ("/plaza/admin/performance", "/plaza/admin/static/screens/overview.js", "/plaza/admin/static/screens/i18n.js"):
            self.assertEqual(self.call("GET", path)[0], 404, path)
            self.assertEqual(self.call("GET", path, headers=ADMIN)[0], 200, path)
            self.assertEqual(self.call("GET", path, headers={**ADMIN, "CF-Connecting-IP": "203.0.113.9"})[0], 404, path)

    def test_unknown_methods_are_refused_as_json(self):
        for method in ("TRACE", "PROPFIND", "FOO"):
            st, body, _ = self.call(method, "/plaza/api/health")
            self.assertEqual(st, 405, method)
            self.assertIn(body["error"], ("bad_request", "not_allowed"))


del ServerTest                       # only this module's own tests run from here


if __name__ == "__main__":
    unittest.main()
