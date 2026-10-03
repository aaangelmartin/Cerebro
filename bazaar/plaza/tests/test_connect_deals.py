"""Connecting a team (browser session, code, agent token, proof in the game) and the thread of every match."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar import supervise
from bazaar.plaza import connect as C
from bazaar.plaza import deals as D
from bazaar.plaza import matcher as M
from bazaar.plaza.store import PlazaError
from bazaar.plaza.tests import test_server as T
from bazaar.plaza.tests.test_matcher import CAT, sheet, sheets


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class ConnectTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.c = C.Connect(Path(self.dir.name) / "connect.json", clock=self.clock)

    def tearDown(self):
        self.dir.cleanup()

    def test_code_is_short_one_use_and_expires(self):
        s = self.c.start("t16", "1.1.1.1")
        self.assertRegex(s["connect_code"], r"^PLAZA-[2-9A-HJ-NP-Z]{6}$")
        with self.assertRaises(PlazaError) as e:
            self.c.agent("t16", "PLAZA-AAAAAA", "2.2.2.2", False)
        self.assertEqual(e.exception.code, "bad_code")
        with self.assertRaises(PlazaError):
            self.c.agent("t15", s["connect_code"], "2.2.2.2", False)          # another team's code
        a = self.c.agent("t16", s["connect_code"].lower(), "2.2.2.2", False)
        self.assertTrue(a["active"])
        self.assertEqual(self.c.auth(a["agent_token"]), ("t16", False))
        with self.assertRaises(PlazaError) as e:
            self.c.agent("t16", s["connect_code"], "2.2.2.2", False)          # one use
        self.assertIn("already used", e.exception.message)
        late = self.c.start("t15", "1.1.1.1")
        self.clock.now += C.CODE_TTL_S + 1
        with self.assertRaises(PlazaError) as e:
            self.c.agent("t15", late["connect_code"], "2.2.2.2", False)
        self.assertIn("expired", e.exception.message)

    def test_nothing_secret_is_stored_in_the_clear(self):
        s = self.c.start("t16", "1.1.1.1")
        a = self.c.agent("t16", s["connect_code"], "2.2.2.2", False)
        raw = (Path(self.dir.name) / "connect.json").read_text()
        self.assertNotIn(s["session"], raw)
        self.assertNotIn(a["agent_token"], raw)

    def test_the_host_cannot_connect_and_attempts_are_limited(self):
        with self.assertRaises(PlazaError) as e:
            self.c.start("t10", "1.1.1.1")
        self.assertEqual(e.exception.status, 403)
        for i in range(C.STARTS_PER_TEAM):
            self.c.start("t16", f"9.9.9.{i}")
        with self.assertRaises(PlazaError) as e:
            self.c.start("t16", "8.8.8.8")                                    # per team
        self.assertEqual(e.exception.status, 429)
        for i in range(C.STARTS_PER_CLIENT):
            self.c.start(f"t0{1 + i % 5}", "7.7.7.7")
        with self.assertRaises(PlazaError):
            self.c.start("t06", "7.7.7.7")                                    # per client
        for _ in range(C.TRIES_PER_CLIENT):
            with self.assertRaises(PlazaError):
                self.c.agent("t01", "PLAZA-222222", "6.6.6.6", False)
        with self.assertRaises(PlazaError) as e:
            self.c.agent("t02", "PLAZA-222222", "6.6.6.6", False)
        self.assertEqual(e.exception.code, "locked")
        self.clock.now += C.WINDOW_S + 1
        self.c.start("t16", "8.8.8.8")                                        # the window passed

    def test_status_heartbeat_and_session_expiry(self):
        s = self.c.start("t16", "1.1.1.1")
        st = self.c.status(s["session"], lambda t: False)
        self.assertEqual(st["missing"], ["agent_called", "verified", "cards_listed", "agent_online"])
        a = self.c.agent("t16", s["connect_code"], "2.2.2.2", False)
        self.c.auth(a["agent_token"])
        self.assertTrue(self.c.prove("t16", f"hello {s['connect_code']} thanks"))
        st = self.c.status(s["session"], lambda t: True)
        self.assertEqual((st["missing"], st["connected"], st["team"]), ([], True, "t16"))
        self.clock.now += C.ONLINE_S + 5
        st = self.c.status(s["session"], lambda t: True)
        self.assertEqual((st["agent_online"], st["connected"]), (False, True))        # stays connected: read only
        self.clock.now += C.SESSION_TTL_S
        with self.assertRaises(PlazaError) as e:
            self.c.status(s["session"], lambda t: True)
        self.assertEqual(e.exception.status, 401)
        self.assertEqual(self.c.auth(a["agent_token"]), ("t16", True))               # the agent keeps working

    def test_a_verified_team_reconnects_only_through_the_game(self):
        s = self.c.start("t16", "1.1.1.1")
        a = self.c.agent("t16", s["connect_code"], "2.2.2.2", False)
        self.c.prove("t16", s["connect_code"])
        thief = self.c.start("t16", "6.6.6.6")
        b = self.c.agent("t16", thief["connect_code"], "6.6.6.6", True)
        self.assertFalse(b["active"])
        with self.assertRaises(PlazaError) as e:
            self.c.auth(b["agent_token"])
        self.assertEqual(e.exception.code, "prove_first")
        self.assertEqual(self.c.auth(a["agent_token"]), ("t16", True))               # the real agent is untouched
        self.assertFalse(self.c.prove("t15", thief["connect_code"]))                  # another team's message
        self.assertTrue(self.c.prove("t16", thief["connect_code"]))                   # the real team reconnects
        self.assertEqual(self.c.auth(b["agent_token"]), ("t16", True))
        with self.assertRaises(PlazaError):
            self.c.auth(a["agent_token"])                                             # replaced

    def test_prompt_is_ready_to_paste(self):
        p = C.prompt("t16", "PLAZA-7K2Q9M", "https://overhead-silicon-cork-citation.example.com/plaza")
        self.assertLessEqual(len(p), 900)
        for piece in ("Team 16", "PLAZA-7K2Q9M", "/agents.md", "/api/connect/agent", "YOUR OWN game key", "t10", "v07",
                      "/api/team/t16"):
            self.assertIn(piece, p)


class MatcherRulesTest(unittest.TestCase):
    def test_price_midpoint_declared_book_and_floor(self):
        self.assertEqual(M.price_for({"price": 90}, {"bid": 50}, "rare"), (70, "midpoint"))
        self.assertEqual(M.price_for({"price": 60}, {}, "rare"), (60, "declared"))
        self.assertEqual(M.price_for({}, {"bid": 55}, "rare"), (55, "declared"))
        self.assertEqual(M.price_for({}, {}, "rare"), (70, "book"))
        self.assertEqual(M.price_for({}, {}, "rare", book=80), (80, "book"))
        self.assertEqual(M.price_for({"price": 12}, {}, "rare"), (40, "floor"))       # never under the floor

    def test_priority_order(self):
        ms = M.find(sheets(sheet("t01", sale=["MAL-11", "RET-03", "LAT-03"], spares=["LAT-06"], wants=["RET-07", "RET-03"]),
                           sheet("t02", wants=["MAL-11", "RET-03", "SAL-02"]),
                           sheet("t03", wants=["LAT-03"]),
                           sheet("t04", spares=["RET-07"], wants=["LAT-06", "LAT-03"])), CAT)
        order = [(m["priority"], m["kind"], m["ref"], m["buyer"]) for m in ms]
        self.assertEqual(order[0][0], 1)                                              # the last card of a page
        self.assertEqual(sorted({p for p, *_ in order}), [1, 2, 3, 4])
        self.assertEqual([p for p, *_ in order], sorted(p for p, *_ in order))
        self.assertIn((2, "swap", "LAT-06", "t04"), order)
        self.assertIn((3, "sale", "MAL-11", "t02"), order)

    def test_one_active_match_per_card_and_team(self):
        ms = M.find(sheets(sheet("t01", sale=["SAL-09"]), sheet("t02", wants=["SAL-09"]),
                           sheet("t03", wants=["SAL-09"]), sheet("t04", wants=["SAL-09"])), CAT)
        self.assertEqual(len(ms), 3)
        active = M.assign(ms)
        self.assertEqual(len(active), 1)                                              # not offered to three at once
        self.assertEqual(len(active[0]["alternatives"]), 2)
        again = M.assign(ms, skip={active[0]["id"]})
        self.assertEqual(again[0]["id"], active[0]["alternatives"][0]["id"])
        self.assertEqual(len({m["id"] for m in ms}), 3)
        self.assertRegex(ms[0]["id"], r"^m-[0-9a-f]{10}$")


def listed(tick, maker, to, ref, price, oid=1):
    return {"t": "listed", "tick": tick, "id": oid, "maker": maker, "to": to, "side": "bid", "ref": ref,
            "ref_back": None, "price": price}


class DealsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = D.Deals(Path(self.dir.name) / "matches.json")
        self.cands = M.find(sheets(sheet("t01", sale=[{"ref": "SAL-09", "price": 60}]), sheet("t02", wants=["SAL-09"]),
                                   sheet("t03", wants=["SAL-09"])), CAT)

    def tearDown(self):
        self.dir.cleanup()

    def test_states_come_from_the_game(self):
        ev = self.d.sync(self.cands, 10, [])
        self.assertEqual([e["state"] for e in ev], ["proposed"])
        m = self.d.live()[0]
        self.assertEqual((m["state"], m["seller"], m["buyer"], m["price"]), ("proposed", "t01", "t02", 60))
        log = [listed(9, "t02", "t01", "SAL-09", 50)]                          # before the proposal: not ours
        self.assertEqual(self.d.sync(self.cands, 11, log), [])
        log.append(listed(12, "t02", "t01", "SAL-09", 55, oid=2))
        ev = self.d.sync(self.cands, 12, log)
        self.assertEqual([(e["state"], e["price"]) for e in ev], [("offer_on_v07", 55)])
        log.append({"t": "cancelled", "tick": 13, "id": 2})
        self.assertEqual(self.d.sync(self.cands, 13, log)[0]["state"], "proposed")
        log.append(listed(14, "t01", "t02", "SAL-09", 58, oid=3))
        self.d.sync(self.cands, 14, log)
        rec, item, _ = self.d.message(m["id"], "t02", True, {"action": "accept"})  # the receiver of the offer accepts
        self.assertEqual((rec["state"], item["kind"]), ("accepted", "accept"))
        log.append({"t": "settled", "tick": 15, "parties": ["t01", "t02"], "refs": ["SAL-09"], "price": 58})
        ev = self.d.sync(self.cands, 15, log)
        self.assertEqual([(e["state"], e["price"]) for e in ev if e["match"] == m["id"]], [("settled", 58)])
        self.assertEqual(self.d.funnel()["settled"], 1)
        self.assertNotIn(m["id"], [r["id"] for r in self.d.live()])            # settled: not proposed again

    def test_a_restart_reads_the_same_story(self):
        self.d.sync(self.cands, 10, [])
        log = [listed(12, "t02", "t01", "SAL-09", 55)]
        self.d.sync(self.cands, 12, log)
        again = D.Deals(self.d.path)
        self.assertEqual(again.sync(self.cands, 13, log), [])                  # replaying the log changes nothing
        self.assertEqual(again.live()[0]["state"], "offer_on_v07")

    def test_negotiation_counter_floor_party_and_pass(self):
        self.d.sync(self.cands, 10, [])
        mid = self.d.live()[0]["id"]
        rec, item, _ = self.d.message(mid, "t02", False, {"action": "counter", "price": 50, "text": " 50 and  done <b>"})
        self.assertEqual((rec["price"], rec["price_by"], rec["agreed"], item["text"]), (50, "t02", ["t02"], "50 and done <b>"))
        for body, code in (({"action": "counter", "price": 10}, "below_floor"), ({"action": "counter"}, "bad_request"),
                           ({"action": "steal"}, "bad_request"), ({"text": "x" * 281}, "bad_request"),
                           ({"action": "accept", "html": "<script>"}, "bad_request"), ({}, "bad_request")):
            with self.assertRaises(PlazaError) as e:
                self.d.message(mid, "t02", False, body)
            self.assertEqual(e.exception.code, code, body)
        with self.assertRaises(PlazaError) as e:
            self.d.message(mid, "t03", False, {"action": "accept"})
        self.assertEqual(e.exception.code, "not_a_party")
        rec, _, _ = self.d.message(mid, "t01", False, {"action": "accept"})
        self.assertEqual((rec["agreed"], rec["state"]), (["t02", "t01"], "proposed"))   # agreed; the game decides
        rec, _, _ = self.d.message(mid, "t01", False, {"action": "pass", "text": "changed my mind"})
        self.assertEqual(rec["state"], "passed")
        with self.assertRaises(PlazaError) as e:
            self.d.message(mid, "t02", False, {"text": "wait"})
        self.assertEqual(e.exception.status, 409)
        self.d.sync(self.cands, 11, [])
        live = self.d.live()
        self.assertEqual([(m["seller"], m["buyer"]) for m in live], [("t01", "t03")])   # the alternative takes over
        self.d.sync(self.cands, 11 + D.PASS_TICKS - 5, [])
        self.assertNotIn(mid, [m["id"] for m in self.d.live()])                         # not repeated yet

    def test_messages_are_limited_per_team(self):
        self.d.sync(self.cands, 10, [])
        mid = self.d.live()[0]["id"]
        for _ in range(D.PER_TEAM_PER_MIN):
            self.d.message(mid, "t02", False, {"text": "hi"})
        with self.assertRaises(PlazaError) as e:
            self.d.message(mid, "t02", False, {"text": "hi"})
        self.assertEqual(e.exception.status, 429)

    def test_proposals_expire_and_come_back_after_a_while(self):
        self.d.sync(self.cands, 10, [])
        mid = self.d.live()[0]["id"]
        ev = self.d.sync(self.cands, 11 + D.PROPOSAL_TICKS, [])
        self.assertIn((mid, "expired"), [(e["match"], e["state"]) for e in ev])
        self.assertEqual(self.d.live()[0]["buyer"], "t03")
        self.d.sync(self.cands[:1], 12 + D.PROPOSAL_TICKS + D.EXPIRED_TICKS, [])
        self.assertEqual([m["id"] for m in self.d.live()], [mid])

    def test_pause_exclude_withdraw_and_force(self):
        self.assertEqual(self.d.sync(self.cands, 10, [], paused=True), [])
        self.assertEqual(self.d.live(), [])
        self.d.sync(self.cands, 10, [], excluded_teams=frozenset({"t02"}))
        self.assertEqual([m["buyer"] for m in self.d.live()], ["t03"])
        self.d.sync([], 11, [])                                                 # the sheets changed
        self.assertEqual(self.d.live(), [])
        forced = dict(self.cands[1])
        self.d.force(forced)
        self.d.sync(self.cands, 12, [])
        live = self.d.live()
        self.assertEqual((len(live), live[0]["id"], live[0]["forced"]), (1, forced["id"], True))
        q = self.d.queue()
        self.assertEqual((len(q["queue"]), q["queue"][0]["why"]), (1, forced["why"]))
        self.d.sync(self.cands, 12 + D.STALL_TICKS + 1, [])
        self.assertEqual(len(self.d.queue()["stalled"]), 1)
        self.assertEqual(self.d.expire(forced["id"])["state"], "expired")


class FlowTest(unittest.TestCase):
    """The whole thing through HTTP: a human starts, the agent connects, the game proves it, the page sees it."""
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call

    def game_says(self, team, text, name="th1"):
        (self.record / "threads" / f"{name}.json").write_text(json.dumps(
            {"id": name, "kind": "team", "messages": [{"sender": team, "text": text}]}) + "\n")
        self.board.verified_at = 0.0

    def connect(self, team):
        st, s, h = self.call("POST", "/plaza/api/connect/start", {"team": team})
        self.assertEqual(st, 200, s)
        st, a, _ = self.call("POST", "/plaza/api/connect/agent", {"team": team, "code": s["connect_code"]})
        self.assertEqual(st, 200, a)
        return s, a["agent_token"], h

    def event(self, **e):
        with (self.live / "events.jsonl").open("a") as f:
            f.write(json.dumps(e) + "\n")
        self.board.tick_feed()

    def test_connection_flow_end_to_end(self):
        st, s, h = self.call("POST", "/plaza/api/connect/start", {"team": "t07"})
        self.assertEqual(st, 200)
        cookie = h["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Path=/plaza", cookie)
        self.assertLessEqual(len(s["prompt"]), 900)
        self.assertIn(s["connect_code"], s["prompt"])
        self.assertIn("Team 7", s["prompt"])
        q = "/plaza/api/connect/status?session=" + s["session"]
        st, status, _ = self.call("GET", q)
        self.assertEqual(status["missing"], ["agent_called", "verified", "cards_listed", "agent_online"])
        self.assertEqual(self.call("GET", "/plaza/api/me?session=" + s["session"])[0], 403)       # not yet
        self.assertEqual(self.call("POST", "/plaza/api/connect/agent", {"team": "t07", "code": "PLAZA-222222"})[0], 403)
        st, a, _ = self.call("POST", "/plaza/api/connect/agent", {"team": "t07", "code": s["connect_code"]})
        self.assertEqual((st, a["header"]), (200, "X-Plaza-Token"))
        token = {"X-Plaza-Token": a["agent_token"]}
        self.assertEqual(self.call("POST", "/plaza/api/connect/agent", {"team": "t07", "code": s["connect_code"]})[0], 403)
        st, d, _ = self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-06"], "spares": ["LAT-03"]}, token)
        self.assertEqual((st, d["declared"]["wants"]), (200, ["LAT-06"]))
        self.assertEqual(self.call("PUT", "/plaza/api/team/t08", {"wants": []}, token)[0], 403)   # another team
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": []}, {"X-Plaza-Token": "x" * 32})[0], 403)
        st, status, _ = self.call("GET", q)
        self.assertEqual(status["missing"], ["verified"])
        self.game_says("t08", s["connect_code"], "other")                                      # somebody else: no
        self.assertEqual(self.call("GET", q)[1]["verified"], False)
        self.game_says("t07", f"hi, {s['connect_code']}")
        st, status, _ = self.call("GET", "/plaza/api/connect/status", headers={"Cookie": cookie.split(";")[0]})
        self.assertEqual((status["missing"], status["connected"], status["team"]), ([], True, "t07"))
        st, me, _ = self.call("GET", "/plaza/api/me", headers={"Cookie": "a=b; " + cookie.split(";")[0]})
        self.assertEqual((st, me["team"], me["read_only"]), (200, "t07", True))
        self.assertEqual([c["ref"] for c in me["home"]["wanted"]], ["LAT-06"])
        self.assertEqual([c["ref"] for c in me["home"]["available"]], ["LAT-03"])
        self.assertTrue(me["home"]["agent_online"])
        self.assertEqual(self.call("GET", "/plaza/api/me")[0], 401)
        self.assertEqual(self.call("GET", "/plaza/api/connect/status?session=../etc")[0], 400)
        row = next(t for t in self.call("GET", "/plaza/api/teams")[1]["teams"] if t["team"] == "t07")
        self.assertEqual((row["claimed"], row["verified"]), (True, True))
        blob = json.dumps(self.call("GET", "/plaza/api/team/t07")[1]) + json.dumps(self.call("GET", "/plaza/api/teams")[1])
        for secret in (s["session"], a["agent_token"], s["connect_code"]):
            self.assertNotIn(secret, blob)
        st, ov, _ = self.call("GET", "/plaza/admin/api/overview", headers={"X-Plaza-Admin": "test-admin-token"})
        t7 = next(t for t in ov["teams"] if t["team"] == "t07")
        self.assertEqual((t7["connected"], t7["verified"], t7["online"], t7["agent"]), (True, True, True, True))
        self.assertIsNotNone(t7["last_sync"])
        self.assertEqual((ov["connected_teams"], ov["online_teams"]), (1, 1))
        self.assertGreaterEqual(ov["hourly"][-1]["connect_start"], 1)
        self.assertIn("proposed", ov["match_funnel"])

    def test_host_expiry_and_reconnect_through_http(self):
        self.assertEqual(self.call("POST", "/plaza/api/connect/start", {"team": "t10"})[0], 403)
        self.assertEqual(self.call("POST", "/plaza/api/connect/start", {"team": "t77"})[0], 400)
        self.assertEqual(self.call("POST", "/plaza/api/connect/start", ["t07"])[0], 400)
        s, token, _ = self.connect("t07")
        self.game_says("t07", s["connect_code"])
        self.assertTrue(self.call("GET", "/plaza/api/connect/status?session=" + s["session"])[1]["verified"])
        s2, token2, _ = self.connect("t07")                                    # somebody asks again for a verified team
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": []}, {"X-Plaza-Token": token2})[1]["error"], "prove_first")
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-06"]}, {"X-Plaza-Token": token})[0], 200)
        self.assertEqual(self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "4242"})[0], 403)   # nor by PIN
        s3 = self.call("POST", "/plaza/api/connect/start", {"team": "t08"})[1]
        real = time.time
        self.board.connect.clock = lambda: real() + C.CODE_TTL_S + 5
        st, out, _ = self.call("POST", "/plaza/api/connect/agent", {"team": "t08", "code": s3["connect_code"]})
        self.assertEqual((st, out["error"]), (403, "bad_code"))
        self.board.connect.clock = lambda: real() + C.SESSION_TTL_S + 5
        self.assertEqual(self.call("GET", "/plaza/api/connect/status?session=" + s3["session"])[0], 401)

    def test_match_thread_from_proposal_to_settlement(self):
        st, home, _ = self.call("GET", "/plaza/api/team/t07")
        trade = home["trades"][0]
        mid = trade["id"]
        self.assertEqual((trade["state"], trade["kind"], trade["price"], trade["saves"]), ("proposed", "sale", 20, 2))
        self.assertEqual([(x["team"], [c["ref"] for c in x["gives"]]) for x in trade["sides"]], [("t09", ["LAT-06"]), ("t07", [])])
        self.assertEqual(trade["sides"][0]["gives"][0]["name"], "La Chulapa")
        self.assertEqual(self.call("GET", "/plaza/api/offers?team=t07")[1]["trades"][0]["id"], mid)
        _, tok7, _ = self.connect("t07")
        _, tok8, _ = self.connect("t08")
        url = f"/plaza/api/match/{mid}/message"
        self.assertEqual(self.call("POST", url, {"action": "counter", "price": 15})[0], 400)       # nobody
        self.assertEqual(self.call("POST", url, {"action": "counter", "price": 15}, {"X-Plaza-Token": tok8})[1]["error"], "not_a_party")
        self.assertEqual(self.call("POST", url, {"action": "counter", "price": 5}, {"X-Plaza-Token": tok7})[1]["error"], "below_floor")
        st, out, _ = self.call("POST", url, {"action": "counter", "price": 15, "text": "15 and we close now"}, {"X-Plaza-Token": tok7})
        self.assertEqual((st, out["match"]["price"], out["match"]["recipe"]["buyer"]["body"]["give"]), (200, 15, {"cash": 15}))
        self.assertEqual(self.call("POST", "/plaza/api/match/m-0000000000/message", {"text": "x"}, {"X-Plaza-Token": tok7})[0], 404)
        floor = self.call("GET", "/plaza/api/floor?kind=counter")[1]["items"]
        self.assertEqual([(i["team"], i["to"], i["price"], i["match"]) for i in floor], [("t07", "t09", 15, mid)])
        offer = {"id": 900, "maker": "t07", "to": "t09", "venue": "v07", "thread": None, "created_tick": 80, "expires_tick": 140,
                 "give": {"cash": 15, "assets": [], "types": []}, "want": {"cash": 0, "assets": [], "types": ["card:LAT-06"]}}
        self.event(tick=80, type="offer.listed", payload={"venue": "v07", "offer": offer})
        st, th, _ = self.call("GET", f"/plaza/api/match/{mid}")
        self.assertEqual((th["state"], th["offer"], len(th["thread"]), th["thread"][0]["text"]), ("offer_on_v07", 900, 1, "15 and we close now"))
        self.call("POST", "/plaza/api/claim", {"team": "t09", "pin": "4242"})                    # the PIN still works
        st, out, _ = self.call("POST", url, {"team": "t09", "action": "accept"}, {"X-Plaza-Pin": "4242"})
        self.assertEqual((st, out["match"]["state"]), (200, "accepted"))
        self.event(tick=81, type="settlement", payload={"venue": "v07", "price": 15, "parties": ["t07", "t09"],
                                                         "items": [{"ref": "LAT-06", "frm": "t09", "to": "t07"}]})
        st, th, _ = self.call("GET", f"/plaza/api/match/{mid}")
        self.assertEqual(([x["state"] for x in th["history"]], th["state"]),
                         (["proposed", "offer_on_v07", "accepted", "settled"], "settled"))
        self.assertEqual(self.call("GET", "/plaza/api/team/t07")[1]["trades"], [])               # done: off the table
        states = [i["state"] for i in self.call("GET", "/plaza/api/floor?kind=match")[1]["items"] if i["match"] == mid]
        self.assertEqual(states[-3:], ["offer_on_v07", "accepted", "settled"])
        st, ov, _ = self.call("GET", "/plaza/admin/api/overview", headers={"X-Plaza-Admin": "test-admin-token"})
        self.assertEqual(ov["match_funnel"]["settled"], 1)

    def test_art_blocked_teams_and_hidden_lines(self):
        st, svg, h = self.call("GET", "/plaza/art/LAT-06.svg")
        if st == 200:                                                          # the dashboard's art is in this checkout
            self.assertIn("image/svg+xml", h["Content-Type"])
            self.assertIn("xmlns", svg[:120])
            self.assertEqual(self.call("GET", "/plaza/api/card/LAT-06")[1]["art"], "/plaza/art/LAT-06.svg")
        for path in ("/plaza/art/ZZZ-99.svg", "/plaza/art/../x.svg", "/plaza/art/LAT-06.png"):
            self.assertEqual(self.call("GET", path)[0], 404, path)
        mid = self.call("GET", "/plaza/api/team/t07")[1]["trades"][0]["id"]
        _, tok7, _ = self.connect("t07")
        admin = {"X-Plaza-Admin": "test-admin-token"}
        url = f"/plaza/api/match/{mid}/message"
        n = self.call("POST", url, {"text": "something rude"}, {"X-Plaza-Token": tok7})[1]["posted"]
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "hide", "match": mid, "message": n}, admin)[0], 200)
        self.assertEqual(self.call("GET", f"/plaza/api/match/{mid}")[1]["thread"], [])
        self.assertEqual([i for i in self.call("GET", "/plaza/api/floor")[1]["items"] if i.get("msg") == n], [])
        self.call("POST", "/plaza/admin/api/action", {"action": "block", "team": "t07"}, admin)
        self.assertEqual(self.call("POST", url, {"text": "again"}, {"X-Plaza-Token": tok7})[1]["error"], "blocked")

    def test_matchmaker_panel_is_ours_only(self):
        admin = {"X-Plaza-Admin": "test-admin-token"}
        self.assertEqual(self.call("GET", "/plaza/admin/api/matchmaker")[0], 404)
        self.assertEqual(self.call("GET", "/plaza/admin/api/matchmaker", headers={"X-Plaza-Admin": "nope"})[0], 404)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "pause"})[0], 404)
        st, mm, _ = self.call("GET", "/plaza/admin/api/matchmaker", headers=admin)
        self.assertEqual((st, len(mm["queue"]), mm["paused"]), (200, 1, False))
        row = mm["queue"][0]
        self.assertEqual((row["seller"], row["buyer"], row["basis"], row["priority"]), ("t09", "t07", "declared", 1))
        self.assertIn("looks for it", row["why"])
        st, out, _ = self.call("POST", "/plaza/admin/api/action", {"action": "exclude", "team": "t09"}, admin)
        self.assertEqual(out["admin"]["excluded_teams"], ["t09"])
        self.assertEqual(self.call("GET", "/plaza/admin/api/matchmaker", headers=admin)[1]["queue"], [])
        self.call("POST", "/plaza/admin/api/action", {"action": "pause"}, admin)
        self.call("POST", "/plaza/admin/api/action", {"action": "include", "team": "t09"}, admin)
        mm = self.call("GET", "/plaza/admin/api/matchmaker", headers=admin)[1]
        self.assertEqual((mm["queue"], mm["paused"]), ([], True))                                # paused: nothing new
        for body in ({"action": "force", "seller": "t10", "buyer": "t07", "ref": "LAT-03"},      # never us
                     {"action": "force", "seller": "t09", "buyer": "t09", "ref": "LAT-03"},
                     {"action": "force", "seller": "t09", "buyer": "t07", "ref": "LAT-13"},      # hidden card
                     {"action": "force", "seller": "t09", "buyer": "t07", "ref": "LAT-03", "price": 1}):
            self.assertEqual(self.call("POST", "/plaza/admin/api/action", body, admin)[0], 400, body)
        st, out, _ = self.call("POST", "/plaza/admin/api/action", {"action": "force", "seller": "t02", "buyer": "t03", "ref": "LAT-03"}, admin)
        self.assertEqual(st, 200)
        mm = self.call("GET", "/plaza/admin/api/matchmaker", headers=admin)[1]
        self.assertEqual([(r["id"], r["forced"], r["price"]) for r in mm["queue"]], [(out["match"], True, 10)])
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "expire", "match": out["match"]}, admin)[1]["state"], "expired")
        self.call("POST", "/plaza/admin/api/action", {"action": "resume"}, admin)
        self.assertEqual(len(self.call("GET", "/plaza/admin/api/matchmaker", headers=admin)[1]["queue"]), 1)


class SuperviseTest(unittest.TestCase):
    def test_the_plaza_is_a_supervised_service(self):
        lock, services, _ = supervise.chosen({})
        self.assertEqual(lock, "supervise")
        plaza = [s for s in services if s.name == "plaza"]
        self.assertEqual(plaza[0].cmd[-2:], ["-m", "bazaar.plaza.server"])
        lock, services, _ = supervise.chosen({"BAZAAR_SUPERVISE_ONLY": "plaza"})
        self.assertEqual((lock, [s.name for s in services]), ("supervise-plaza", ["plaza"]))     # the others untouched
        with self.assertRaises(SystemExit):
            supervise.chosen({"BAZAAR_SUPERVISE_ONLY": "nothing"})


if __name__ == "__main__":
    unittest.main()
