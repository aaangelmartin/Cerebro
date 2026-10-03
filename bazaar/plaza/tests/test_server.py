"""The plaza is public: only its own routes answer, input is validated, and nothing private leaks."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bazaar.plaza import server as S

CATALOG = {"sets": [{"id": "LAT", "name": "La Latina", "color": "#F2A541", "released": True, "cards": [
    {"id": "LAT-06", "name": "La Chulapa", "rarity": "uncommon"}, {"id": "LAT-03", "name": "Huevos Rotos", "rarity": "common"},
    {"id": "LAT-13", "name": "Hidden", "rarity": "legendary", "hidden": True}]}],
    "rarities": {"common": {"book": 10}, "uncommon": {"book": 25}}}
REPORT = {"tick": 77, "rivals": {
    "t09": {"name": "Team 9", "pages": 2, "album": "30/50", "selling": {"LAT-06": {"ask": 20, "venue": "rastro", "offer": 5}}},
    "t07": {"name": "Team 7", "hunting": {"LAT-06": {"dealer_threads": 2}}}}}


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.live, self.record = root / "live", root / "record"
        (self.record / "latest").mkdir(parents=True)
        (self.record / "threads").mkdir()
        self.live.mkdir()
        (self.record / "latest" / "catalog.json").write_text(json.dumps(CATALOG))
        (self.live / "control.json").write_text(json.dumps({"armed": True, "secret_thing": "hunter2"}))
        (self.live / "events.jsonl").write_text(
            json.dumps({"tick": 5, "type": "settlement", "payload": {"venue": "v07", "price": 20}}) + "\n"
            + json.dumps({"tick": 6, "type": "settlement", "payload": {"venue": "rastro", "price": 99}}) + "\n")
        self.board = S.Board(self.live, self.record, report_fn=lambda: REPORT)
        self.srv = S.make_server(self.board, port=0)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.dir.cleanup()

    def call(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json"} if body is not None else {}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={**h, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if "json" in r.headers.get("Content-Type", "") else raw.decode()), r.headers
        except urllib.error.HTTPError as e:
            raw = e.read()
            e.close()
            try:
                return e.code, json.loads(raw), e.headers
            except ValueError:
                return e.code, raw.decode(errors="replace"), e.headers

    def test_teams_team_matches_wall(self):
        st, teams, _ = self.call("GET", "/plaza/api/teams")
        self.assertEqual((st, len(teams["teams"]), teams["tick"]), (200, 18, 77))
        self.assertEqual(teams["stats"], {"venue": "v07", "deals": 1, "volume": 20, "saved_fees": 2, "last_deal_tick": 5})
        host = next(t for t in teams["teams"] if t["team"] == "t10")
        self.assertTrue(host["host"])
        st, t7, _ = self.call("GET", "/plaza/api/team/t07")
        self.assertEqual([w["ref"] for w in t7["wants"]], ["LAT-06"])
        self.assertEqual(t7["wants"][0]["name"], "La Chulapa")
        self.assertEqual((t7["matches"][0]["seller"], t7["matches"][0]["price"]), ("t09", 20))
        st, ms, _ = self.call("GET", "/plaza/api/matches?team=t09")
        self.assertEqual((st, ms["total"]), (200, 1))
        st, wall, _ = self.call("GET", "/plaza/api/wall")
        self.assertEqual((wall["wanted"][0]["ref"], wall["wanted"][0]["sellers"][0]["team"]), ("LAT-06", "t09"))

    def test_page_static_and_agents_doc(self):
        st, html, h = self.call("GET", "/plaza/")
        self.assertEqual(st, 200)
        self.assertIn("Plaza", html)
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(self.call("GET", "/plaza/static/plaza.js")[0], 200)
        st, md, _ = self.call("GET", "/plaza/agents.md")
        self.assertIn("X-Plaza-Pin", md)
        self.assertIn("Never send your game key", md)

    def test_only_whitelisted_routes_answer(self):
        for path in ("/", "/control", "/brain/chat", "/outbox", "/plaza/static/../server.py", "/plaza/static/x.js",
                     "/plaza/api/team/t99x", "/plaza/api/nope", "/plaza/../etc/passwd", "/plaza/api/team/t77",
                     "/plaza/web/index.html", "/plaza/api/control"):
            self.assertEqual(self.call("GET", path)[0], 404, path)
        self.assertEqual(self.call("GET", "/plaza/api/matches?team=../x")[0], 400)
        for method in ("DELETE", "PATCH", "OPTIONS"):
            self.assertEqual(self.call(method, "/plaza/api/team/t07")[0], 405)

    def test_nothing_private_leaks(self):
        blob = ""
        for path in ("/plaza/api/teams", "/plaza/api/team/t09", "/plaza/api/matches", "/plaza/api/wall", "/plaza/api/health"):
            blob += json.dumps(self.call("GET", path)[1])
        self.call("POST", "/plaza/api/claim", {"team": "t09", "pin": "4242"})
        blob += json.dumps(self.call("GET", "/plaza/api/team/t09")[1]) + json.dumps(self.call("GET", "/plaza/api/teams")[1])
        for secret in ("hunter2", "secret_thing", "armed", "4242", "PLAZA-", "salt", "LAT-13"):
            self.assertNotIn(secret, blob)

    def test_claim_declare_and_see_it(self):
        st, c, _ = self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})
        self.assertEqual(st, 200)
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-03"]})[0], 403)
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-03"]}, {"X-Plaza-Pin": "0000"})[1]["error"], "bad_pin")
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-03"], "spares": ["LAT-06"]}, {"X-Plaza-Pin": "4242"})
        self.assertEqual((st, out["declared"]["wants"]), (200, ["LAT-03"]))
        t7 = self.call("GET", "/plaza/api/team/t07")[1]
        self.assertEqual([(w["ref"], w["source"]) for w in t7["wants"]], [("LAT-03", "agent")])
        self.assertTrue(t7["claimed"])
        self.assertFalse(t7["verified"])
        # the team proves the claim with a thread message to us in the game
        (self.record / "threads" / "9.json").write_text(json.dumps(
            {"id": 9, "kind": "team", "team": "t07", "with": "t10", "messages": [{"sender": "t07", "text": f"hi {c['code']}"}]}))
        self.board.rebuild()
        self.assertTrue(self.call("GET", "/plaza/api/team/t07")[1]["verified"])

    def test_a_message_from_another_team_does_not_verify(self):
        c = self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})[1]
        (self.record / "threads" / "9.json").write_text(json.dumps(
            {"id": 9, "kind": "team", "team": "t09", "with": "t10", "messages": [{"sender": "t09", "text": c["code"]}]}))
        self.board.rebuild()
        self.assertFalse(self.call("GET", "/plaza/api/team/t07")[1]["verified"])

    def test_bad_writes(self):
        self.assertEqual(self.call("POST", "/plaza/api/claim", {"team": "t10", "pin": "4242"})[0], 403)
        self.assertEqual(self.call("POST", "/plaza/api/claim", {"team": "t07"})[0], 400)
        self.assertEqual(self.call("POST", "/plaza/api/claim", ["t07"])[0], 400)
        self.assertEqual(self.call("POST", "/plaza/api/teams", {})[0], 404)
        req = urllib.request.Request(self.base + "/plaza/api/claim", data=b"{}", method="POST", headers={"Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        e.exception.close()
        self.assertEqual(e.exception.code, 415)
        big = urllib.request.Request(self.base + "/plaza/api/claim", data=b"x" * (S.MAX_BODY + 1), method="POST",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(big, timeout=5)
        e.exception.close()
        self.assertEqual(e.exception.code, 413)

    def test_switch_and_budget(self):
        (self.live / "control.json").write_text(json.dumps({"plaza": "off"}))
        self.assertEqual(self.call("GET", "/plaza/api/teams")[0], 503)
        self.assertEqual(self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})[0], 503)
        self.assertEqual(self.call("GET", "/plaza/")[0], 200)              # the page itself still loads
        b = S.Budget(clock=lambda: 0.0)
        self.assertTrue(all(b.take("1.2.3.4", "write") for _ in range(S.WRITES_PER_MIN)))
        self.assertFalse(b.take("1.2.3.4", "write"))
        self.assertTrue(b.take("5.6.7.8", "write"))                        # another client has its own budget
        self.assertTrue(b.take("1.2.3.4", "read"))

    def test_public_url(self):
        (self.live / "control.json").write_text(json.dumps({"plaza_url": "https://example.org/plaza/"}))
        self.assertEqual(S.public_url(self.live), "https://example.org/plaza")
        (self.live / "control.json").write_text("{}")
        (self.live.parent / "cloudflared.out").write_text("x https://old-one.trycloudflare.com y\nhttps://new-two.trycloudflare.com")
        self.assertEqual(S.public_url(self.live), "https://new-two.trycloudflare.com/plaza")

    def test_declared_pairs_for_the_matchmaker(self):
        self.assertEqual(S.declared_pairs(self.live, self.record), [])
        for team, body in (("t07", {"wants": ["LAT-06"]}), ("t09", {"for_sale": [{"ref": "LAT-06", "price": 18}]})):
            self.call("POST", "/plaza/api/claim", {"team": team, "pin": "4242"})
            self.call("PUT", f"/plaza/api/team/{team}", body, {"X-Plaza-Pin": "4242"})
        pairs = S.declared_pairs(self.live, self.record)
        self.assertEqual([(p["seller"], p["buyer"], p["ref"], p["price"]) for p in pairs], [("t09", "t07", "LAT-06", 18)])


if __name__ == "__main__":
    unittest.main()
