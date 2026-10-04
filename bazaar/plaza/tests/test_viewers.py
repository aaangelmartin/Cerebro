"""A team's human gets in and stays in: the browser that asks for a new code keeps its session, a viewer link opens
another device to watch only, and a code somebody else fished inherits nobody's browser."""
import tempfile
import unittest
from pathlib import Path

import re
import urllib.request

from bazaar.plaza import connect as C
from bazaar.plaza.store import PlazaError
from bazaar.plaza.tests import test_hardening as H


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class ViewerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.c = C.Connect(Path(self.tmp.name) / "connect.json", clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, team="t16", client="1.1.1.1", keep=None):
        s = self.c.start(team, client, tick=100, keep=keep)
        token = self.c.agent(team, s["connect_code"], client, False)["agent_token"]
        self.assertTrue(self.c.prove(team, s["connect_code"], 100))
        return s, token

    def test_the_browser_that_asks_for_a_new_code_stays_in(self):
        first, _ = self.connect()
        self.assertEqual(self.c.team_of(session=first["session"]), "t16")
        again = self.c.start("t16", "1.1.1.1", tick=120, keep=first["session"])     # the same browser, a new agent
        self.assertTrue(again["kept"])
        self.assertEqual(self.c.team_of(session=first["session"]), "t16")           # still in while the code waits
        self.c.agent("t16", again["connect_code"], "9.9.9.9", True)
        self.assertTrue(self.c.prove("t16", again["connect_code"], 121))
        self.assertEqual(self.c.team_of(session=first["session"]), "t16")           # and after the new proof

    def test_a_fished_code_inherits_no_browser(self):
        mine, _ = self.connect()
        thief = self.c.start("t16", "6.6.6.6", tick=130)                             # no cookie of ours: nothing kept
        self.assertFalse(thief["kept"])
        other = self.c.start("t16", "6.6.6.6", tick=130, keep="x" * 32)              # nor with a made-up cookie
        self.assertFalse(other["kept"])
        self.c.agent("t16", thief["connect_code"], "6.6.6.6", True)
        self.assertTrue(self.c.prove("t16", thief["connect_code"], 131))             # the team was talked into it
        self.assertIsNone(self.c.team_of(session=mine["session"]))                   # ours is out, as before
        back, _ = self.connect()                                                     # we take the team back
        self.assertIsNone(self.c.team_of(session=thief["session"]))                  # and the thief's browser is out

    def test_a_viewer_link_opens_once_and_only_watches(self):
        _, token = self.connect()
        link = self.c.viewer_link("t16")
        self.assertEqual(link["expires_in"], int(C.LINK_TTL_S))
        v = self.c.viewer_open(link["code"])
        self.assertEqual((v["team"], self.c.team_of(session=v["session"])), ("t16", "t16"))
        self.assertTrue(self.c.is_viewer(v["session"]))
        with self.assertRaises(PlazaError) as e:                                     # one use
            self.c.viewer_open(link["code"])
        self.assertEqual(e.exception.code, "bad_link")
        late = self.c.viewer_link("t16")
        self.clock.now += C.LINK_TTL_S + 1
        with self.assertRaises(PlazaError):                                          # ten minutes
            self.c.viewer_open(late["code"])
        with self.assertRaises(PlazaError):
            self.c.viewer_open("not-a-link")
        self.assertFalse(self.c.start("t16", "1.1.1.1", tick=140, keep=v["session"])["kept"])   # a viewer starts nothing

    def test_a_viewer_survives_a_restart_and_dies_with_a_new_proof(self):
        _, token = self.connect()
        v = self.c.viewer_open(self.c.viewer_link("t16")["code"])
        again = C.Connect(Path(self.tmp.name) / "connect.json", clock=self.clock)                     # the process starts again
        self.assertEqual(again.team_of(session=v["session"]), "t16")
        s = again.start("t16", "2.2.2.2", tick=150)
        again.agent("t16", s["connect_code"], "2.2.2.2", True)
        self.assertTrue(again.prove("t16", s["connect_code"], 151))                  # the team changes hands
        self.assertIsNone(again.team_of(session=v["session"]))
        pending = again.viewer_link("t16")
        again.reset("t16")                                                           # ours: nothing of it opens
        with self.assertRaises(PlazaError):
            again.viewer_open(pending["code"])

    def test_one_team_s_link_never_opens_another(self):
        self.connect("t16")
        self.connect("t05", "3.3.3.3")
        v = self.c.viewer_open(self.c.viewer_link("t05")["code"])
        self.assertEqual(self.c.team_of(session=v["session"]), "t05")
        with self.assertRaises(PlazaError):                                          # a team nobody proved has no links
            self.c.viewer_open(self.c.viewer_link("t07")["code"])


class OverHttpTest(H.Base):
    def test_the_agent_asks_for_a_link_and_the_other_device_only_watches(self):
        _, agent = self.agent("t07")
        self.assertEqual(self.call("POST", "/plaza/api/me/viewer-link", [1], agent)[0], 400)      # a JSON object
        self.assertEqual(self.call("POST", "/plaza/api/me/viewer-link", {})[0], 401)              # nobody: no link
        st, link, _ = self.call("POST", "/plaza/api/me/viewer-link", {}, agent)
        self.assertEqual((st, link["team"], link["once"]), (200, "t07", True))
        key = re.search(r"/view\?key=([A-Za-z0-9_-]{20,64})$", link["url"]).group(1)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        host = "http://%s:%s" % self.srv.server_address[:2]
        opener = urllib.request.build_opener(NoRedirect)

        def open_link():
            try:
                opener.open(host + "/plaza/view?key=" + key, timeout=5)
            except urllib.error.HTTPError as e:
                return e.code, e.headers.get("Location"), e.headers.get("Set-Cookie") or ""
        code, where, cookie = open_link()
        self.assertEqual((code, where), (302, "/plaza/home"))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Max-Age=%d" % int(C.SESSION_TTL_S), cookie)
        viewer = {"Cookie": cookie.split(";")[0]}
        st, me, _ = self.call("GET", "/plaza/api/me", None, viewer)                                 # it reads its team
        self.assertEqual((st, me.get("team")), (200, "t07"))
        for method, path, body in (("POST", "/plaza/api/me/settings", {"paused": True}),
                                   ("POST", "/plaza/api/me/card/LAT-06", {"max": 5}),
                                   ("POST", "/plaza/api/me/viewer-link", {})):
            st, out, _ = self.call(method, path, body, dict(viewer, Origin=host))
            self.assertEqual((st, out.get("error")), (403, "viewer"), path)
        self.assertEqual(open_link()[:2], (302, "/plaza/connect?link=expired"))                     # one use
        st, other, _ = self.call("GET", "/plaza/api/me/cards", None, viewer)
        self.assertEqual(st, 200)
        self.assertEqual(self.call("GET", "/plaza/api/team/t05", None, viewer)[0], 200)             # public, as anybody


if __name__ == "__main__":
    unittest.main()
