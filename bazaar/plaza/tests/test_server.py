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
            json.dumps({"tick": 5, "type": "settlement", "payload": {"venue": "v07", "price": 20, "parties": ["t01", "t02"],
                                                                     "items": [{"ref": "LAT-03", "frm": "t01", "to": "t02"}]}}) + "\n"
            + json.dumps({"tick": 6, "type": "settlement", "payload": {"venue": "rastro", "price": 99}}) + "\n")
        (self.record / "latest" / "books").mkdir()
        self.board = S.Board(self.live, self.record, report_fn=lambda: REPORT)
        self.board.token = "test-admin-token"
        self.board.start_feed()
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
        self.assertEqual((st, len(teams["teams"]), teams["tick"]), (200, 18, 6))
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

    def event(self, **e):
        with (self.live / "events.jsonl").open("a") as f:
            f.write(json.dumps(e) + "\n")

    def offer(self, oid, maker, give, want, to=None, venue="rastro", tick=7):
        self.event(id=oid, ts=float(oid), tick=tick, type="offer.listed", payload={"venue": venue, "offer": {
            "id": oid, "maker": maker, "to": to, "venue": venue, "thread": None, "give": give, "want": want,
            "created_tick": tick, "expires_tick": tick + 60}})

    def test_team_home_in_one_call(self):
        self.offer(101, "t03", {"cash": 0, "assets": [{"ref": "LAT-06"}]}, {"cash": 20})              # sells what t07 wants
        self.offer(102, "t03", {"cash": 0, "assets": [{"ref": "LAT-03"}]}, {"cash": 9}, to="t09")     # addressed to another
        self.offer(103, "t04", {"cash": 30}, {"cash": 0, "types": ["card:LAT-06"]}, venue="v07")      # bids for what t09 sells
        self.offer(104, "t07", {"cash": 0, "assets": [{"ref": "LAT-03"}]}, {"cash": 5})               # its own offer
        self.board.tick_feed()
        st, home, _ = self.call("GET", "/plaza/api/team/t07")
        self.assertEqual(st, 200)
        self.assertEqual([(e["ref"], e["finishes_page"]) for e in home["looking_for"]], [("LAT-06", True)])
        self.assertEqual(home["available"], [])
        mine = home["offers_for_you"]
        self.assertEqual([o["id"] for o in mine], [101])
        self.assertEqual((mine[0]["maker"], mine[0]["price"], mine[0]["fee"], mine[0]["cost"]), ("t03", 20, 2, 22))
        self.assertTrue(mine[0]["finishes_page"])
        self.assertEqual(mine[0]["recipe"], {"method": "POST", "path": "/api/offers/101/accept", "body": {}})
        self.assertEqual(home["matches"][0]["seller"], "t09")
        t9 = self.call("GET", "/plaza/api/team/t09")[1]
        self.assertEqual([a["ref"] for a in t9["available"]], ["LAT-06"])
        self.assertEqual([(o["id"], o["side"], o["nets"], o["addressed_to_you"]) for o in t9["offers_for_you"]],
                         [(102, "ask", None, True), (103, "bid", 30, False)])
        self.assertEqual(t9["offers_for_you"][1]["recipe"]["body"], {"assets": ["<your asset id of LAT-06>"]})
        self.assertEqual(self.call("GET", "/plaza/api/team/t10")[1]["offers_for_you"], [])

    def test_market_board_and_card_detail(self):
        self.offer(101, "t03", {"cash": 0, "assets": [{"ref": "LAT-06"}]}, {"cash": 20})
        self.offer(103, "t04", {"cash": 30}, {"cash": 0, "types": ["card:LAT-06"]}, venue="v07")
        self.offer(105, "t05", {"cash": 0, "assets": [{"ref": "LAT-03"}]}, {"cash": 8})
        self.event(id=110, ts=110.0, tick=8, type="offer.cancelled", payload={"offer": 105, "venue": "rastro"})
        self.event(id=111, ts=111.0, tick=8, type="settlement", payload={"venue": "rastro", "price": 18, "parties": ["t03", "t08"],
                   "items": [{"ref": "LAT-06", "frm": "t03", "to": "t08"}]})
        self.board.tick_feed()
        st, board, _ = self.call("GET", "/plaza/api/offers")
        self.assertEqual((st, sorted(o["id"] for o in board["offers"])), (200, [101, 103]))
        ask = next(o for o in board["offers"] if o["id"] == 101)
        self.assertEqual((ask["cost"], ask["rastro_fee"], ask["name"], ask["rarity"]), (22, 2, "La Chulapa", "uncommon"))
        self.assertEqual(next(o for o in board["offers"] if o["id"] == 103)["fee"], 0)                # v07 charges nothing
        self.assertEqual([o["id"] for o in self.call("GET", "/plaza/api/offers?side=bid&venue=v07")[1]["offers"]], [103])
        self.assertEqual(self.call("GET", "/plaza/api/offers?set=RET")[1]["total"], 0)
        self.assertEqual(self.call("GET", "/plaza/api/offers?team=t03")[1]["total"], 1)
        for bad in ("set=lat", "rarity=shiny", "venue=../x", "side=x", "team=10"):
            self.assertEqual(self.call("GET", "/plaza/api/offers?" + bad)[0], 400, bad)
        st, card, _ = self.call("GET", "/plaza/api/card/LAT-06")
        self.assertEqual((st, card["name"], card["last_price"]), (200, "La Chulapa", 18))
        self.assertEqual([h["team"] for h in card["holders"]], ["t09"])
        self.assertEqual([(k["team"], k["finishes_page"]) for k in card["seekers"]], [("t07", True)])
        self.assertEqual(sorted(o["id"] for o in card["offers"]), [101, 103])
        self.assertEqual((card["sales"][0]["from"], card["sales"][0]["to"]), ("t03", "t08"))
        self.assertEqual(self.call("GET", "/plaza/api/card/LAT-13")[0], 404)                         # hidden cards stay hidden
        self.assertEqual(self.call("GET", "/plaza/api/card/XXX-01")[0], 404)

    def test_floor_post_poll_filters_and_moderation(self):
        self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})
        pin = {"X-Plaza-Pin": "4242"}
        self.assertEqual(self.call("POST", "/plaza/api/floor", {"team": "t07", "kind": "want", "ref": "LAT-06"})[0], 403)
        st, out, _ = self.call("POST", "/plaza/api/floor", {"team": "t07", "kind": "want", "ref": "LAT-06", "price": 15,
                                                            "text": "  <b>last</b>\none  "}, pin)
        self.assertEqual((st, out["posted"]["text"], out["posted"]["team"]), (200, "<b>last</b> one", "t07"))
        mid = out["posted"]["id"]
        for bad in ({"kind": "shout", "text": "x"}, {"kind": "want"}, {"kind": "note"}, {"kind": "note", "text": "x" * 281},
                    {"kind": "offer", "ref": "LAT-06", "price": 0}, {"kind": "note", "text": "x", "html": "<i>"},
                    {"kind": "note", "text": "x", "to": "t07"}, {"kind": "note", "text": 5}):
            self.assertEqual(self.call("POST", "/plaza/api/floor", {"team": "t07", **bad}, pin)[0], 400, bad)
        self.event(id=120, ts=9e9, tick=9, type="settlement", payload={"venue": "v07", "price": 12, "parties": ["t03", "t04"],
                   "items": [{"ref": "LAT-03", "frm": "t03", "to": "t04"}]})
        self.board.tick_feed()
        st, got, _ = self.call("GET", "/plaza/api/floor?since=0")
        kinds = [(m["src"], m["kind"]) for m in got["items"]]
        self.assertIn(("agent", "want"), kinds)
        self.assertIn(("game", "deal"), kinds)
        self.assertTrue(next(m for m in got["items"] if m["kind"] == "deal" and m["ref"] == "LAT-03")["highlight"])
        self.assertEqual(self.call("GET", f"/plaza/api/floor?since={got['seq']}")[1]["items"], [])
        self.assertEqual([m["src"] for m in self.call("GET", "/plaza/api/floor?team=t07")[1]["items"]], ["agent"])
        self.assertEqual([m["kind"] for m in self.call("GET", "/plaza/api/floor?kind=want")[1]["items"]], ["want"])
        self.assertEqual(len(self.call("GET", "/plaza/api/floor?ref=LAT-03")[1]["items"]), 2)      # the fixture's deal and this one
        self.assertEqual(self.call("GET", "/plaza/api/floor?since=abc")[0], 400)
        admin = {"X-Plaza-Admin": "test-admin-token"}
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "hide", "message": mid}, admin)[0], 200)
        self.assertEqual(self.call("GET", "/plaza/api/floor?kind=want")[1]["items"], [])
        act = self.call("GET", "/plaza/admin/api/activity", headers=admin)[1]
        self.assertTrue(next(m for m in act["items"] if m.get("id") == mid)["hidden"])
        self.call("POST", "/plaza/admin/api/action", {"action": "unhide", "message": mid}, admin)
        self.call("POST", "/plaza/admin/api/action", {"action": "block", "team": "t07"}, admin)
        self.assertEqual(self.call("GET", "/plaza/api/floor?kind=want")[1]["items"], [])
        self.assertEqual(self.call("POST", "/plaza/api/floor", {"team": "t07", "kind": "note", "text": "hi"}, pin)[1]["error"], "blocked")

    def test_floor_rate_per_team(self):
        self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})
        codes = [self.call("POST", "/plaza/api/floor", {"team": "t07", "kind": "note", "text": f"n{i}"}, {"X-Plaza-Pin": "4242"})[0]
                 for i in range(13)]
        self.assertEqual((codes[:12], codes[12]), ([200] * 12, 429))

    def test_floor_stream(self):
        import http.client
        self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        conn.request("GET", "/plaza/api/floor/stream?since=0")
        r = conn.getresponse()
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "text/event-stream; charset=utf-8"))
        self.call("POST", "/plaza/api/floor", {"team": "t07", "kind": "note", "text": "live now"}, {"X-Plaza-Pin": "4242"})
        seen = b""
        while b"live now" not in seen:
            seen += r.fp.readline()
        self.assertIn(b"event: hello", seen)
        self.assertIn(b"\nid: ", seen)
        conn.close()

    def test_admin_needs_the_token(self):
        for path in ("/plaza/admin/", "/plaza/admin/api/overview", "/plaza/admin/api/activity", "/plaza/admin/static/admin.js"):
            self.assertEqual(self.call("GET", path)[0], 404, path)
            self.assertEqual(self.call("GET", path, headers={"X-Plaza-Admin": "wrong"})[0], 404, path)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "off"})[0], 404)
        admin = {"X-Plaza-Admin": "test-admin-token"}
        self.assertEqual(self.call("GET", "/plaza/admin/", headers=admin)[0], 200)
        self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})
        self.call("GET", "/plaza/api/nope")
        st, o, _ = self.call("GET", "/plaza/admin/api/overview", headers=admin)
        self.assertEqual((st, o["active_teams"], o["verified_teams"], len(o["teams"])), (200, 1, 0, 17))
        self.assertEqual(o["funnel"]["deals_on_venue"], 1)
        self.assertGreaterEqual(o["totals"]["errors"], 1)
        self.assertIn("claim", o["requests"])
        sheet = self.call("GET", "/plaza/admin/api/activity?team=t07", headers=admin)[1]["sheet"]
        self.assertNotIn("pin", sheet)
        self.assertNotIn("salt", sheet)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "off"}, admin)[1]["admin"]["enabled"], False)
        self.assertEqual(self.call("GET", "/plaza/api/teams")[0], 503)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "on"}, admin)[0], 200)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "refresh"}, admin)[0], 200)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "rm -rf"}, admin)[0], 400)
        self.assertEqual(self.call("GET", "/plaza/api/teams")[0], 200)

    def test_deep_links_serve_the_page(self):
        for path in ("/plaza/team/t02", "/plaza/card/LAT-06", "/plaza/floor", "/plaza/market", "/plaza/wall", "/plaza/agents"):
            st, html, _ = self.call("GET", path)
            self.assertEqual(st, 200, path)
            self.assertIn("/plaza/static/plaza.js", html)
        self.assertEqual(self.call("GET", "/plaza/team/t2")[0], 404)
        md = self.call("GET", "/plaza/agents.md")[1]
        for needle in ("/api/floor", "/api/offers", "/api/card/", "offers_for_you", "PLAZA-1A2B3C", "curl -X PUT"):
            self.assertIn(needle, md)

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
