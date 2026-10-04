"""Warnings and the ban: a trade we matched that its maker closes on another venue."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.plaza import safe
from bazaar.plaza.store import PlazaError
from bazaar.plaza.strikes import Strikes, action_id
from bazaar.plaza.tests import test_deals_api as DA
from bazaar.plaza.tests import test_server as T

ADMIN = {"X-Plaza-Admin": "test-admin-token"}
BOTH = {"t01", "t02"}


class RuleTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "plaza_strikes.json"
        self.s = Strikes(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def hit(self, key="m-1|9", maker="t01", parties=("t01", "t02"), verified=BOTH, saw=BOTH, s=None, **kw):
        return (s or self.s).record(key, match=key.split("|")[0], ref="SAL-09", venue="rastro", tick=40,
                                    parties=list(parties), maker=maker, verified=verified, saw=saw, settlement=9,
                                    offer=7, **kw)

    def test_the_first_is_a_warning_and_the_second_a_ban(self):
        out = self.hit()
        self.assertEqual([(e["team"], e["kind"]) for e in out], [("t01", "warning"), ("t02", "notice")])
        st = self.s.standing("t01")
        self.assertEqual((st["strikes"], st["limit"], st["banned"], st["acked"]), (1, 2, False, False))
        self.assertEqual(st["last"], {"match": "m-1", "card": "SAL-09", "venue": "rastro", "tick": 40, "with": "t02",
                                      "seller": "t01", "buyer": "t02"})
        self.assertEqual(st["evidence"], [st["last"]])
        self.assertIn("Warning 1 of 2", st["message"])
        self.assertIn("One more deal closed elsewhere", st["message"])
        self.assertFalse(self.s.banned("t01"))
        out = self.hit("m-2|11")
        self.assertEqual([(e["team"], e["kind"]) for e in out], [("t01", "banned"), ("t02", "notice")])
        self.assertTrue(self.s.banned("t01"))
        self.assertEqual(self.s.banned_teams(), frozenset({"t01"}))
        self.assertIn("no longer has access", self.s.standing("t01")["message"])

    def test_the_team_that_only_accepted_is_told_not_struck(self):
        self.hit()
        st = self.s.standing("t02")
        self.assertEqual((st["strikes"], st["banned"], st["message"], st["last"]), (0, False, None, None))
        self.s.configure(accepter=True)                        # unless we say both count
        out = self.hit("m-2|11")
        self.assertEqual(sorted((e["team"], e["kind"]) for e in out), [("t01", "banned"), ("t02", "warning")])

    def test_one_closing_counts_once_whatever_the_restarts(self):
        self.hit()
        self.assertEqual(self.hit(), [])
        again = Strikes(self.path)                             # a restart reads the same file
        self.assertEqual(self.hit(s=again), [])
        self.assertEqual((again.standing("t01")["strikes"], again.limit, again.on), (1, 2, True))
        self.assertTrue(safe.bak(self.path).exists() or self.path.exists())
        self.path.write_text("{ broken")                       # a write cut half way: the backup still has it
        self.hit("m-0|1", maker="t05", parties=("t05", "t06"), verified={"t05", "t06"}, saw={"t05", "t06"})
        self.assertEqual(Strikes(self.path).standing("t05")["strikes"], 1)

    def test_what_is_not_a_strike(self):
        for kw, why in (({"maker": None}, "unknown"),                                  # the feed does not say who
                        ({"verified": {"t02"}}, "not connected"),                      # never connected and proved
                        ({"saw": {"t02"}}, "not seen"),                                # its agent never saw the proposal
                        ({"predates": True}, "predates")):                             # the offer was already open
            s = Strikes(Path(self.dir.name) / f"{why}.json")
            out = self.hit(s=s, **kw)
            self.assertFalse([e for e in out if e["kind"] in ("warning", "banned")], why)
            self.assertEqual(s.standing("t01")["strikes"], 0, why)
            self.assertTrue(s.view()["log"], why)                                      # but we are told
        self.assertEqual([e["kind"] for e in self.hit("m-9|1", maker=None)], ["unknown"])
        self.assertEqual(self.hit("m-8|1", maker="t10", parties=("t10", "t02")), [])   # the host is never struck

    def test_switched_off_nothing_counts_and_a_rule_ban_does_not_hold(self):
        self.hit()
        self.hit("m-2|11")
        self.assertTrue(self.s.banned("t01"))
        self.s.configure(on=False)
        self.assertFalse(self.s.banned("t01"))
        self.assertEqual(self.hit("m-3|12", maker="t02"), [])
        self.assertEqual((self.s.standing("t02")["strikes"], self.s.actions("t01")), (0, []))
        self.s.ban("t02", "abuse")                             # a ban by hand holds either way
        self.assertTrue(self.s.banned("t02"))
        self.s.configure(on=True)
        self.assertEqual(self.hit("m-3|12", maker="t02"), [])  # and what happened while it was off stays uncounted
        self.assertTrue(self.s.banned("t01"))

    def test_forgive_lift_and_ban_by_hand(self):
        self.hit()
        self.hit("m-2|11")
        self.assertEqual(self.s.unban("t01"), {"strikes": 1, "limit": 2, "banned": False})     # one short of the limit
        self.hit("m-3|12")
        self.assertTrue(self.s.banned("t01"))                  # the next one bans again
        self.assertEqual(self.s.forgive("t01"), {"strikes": 1, "limit": 2, "banned": False})   # without its strikes, no ban
        self.assertEqual(self.s.forgive("t01"), {"strikes": 0, "limit": 2, "banned": False})
        for call in (lambda: self.s.forgive("t01"), lambda: self.s.unban("t01"), lambda: self.s.ban("t10"),
                     lambda: self.s.ban("x"), lambda: self.s.configure(limit=0), lambda: self.s.configure(on="yes"),
                     lambda: self.s.configure(), lambda: self.s.forgive("t02", "a-000000000000")):
            self.assertRaises(PlazaError, call)
        self.assertEqual(self.s.configure(limit=3), {"on": True, "limit": 3, "accepter": False})
        self.assertEqual(Strikes(self.path).limit, 3)

    def test_the_agent_reads_its_warning_once(self):
        self.hit()
        (a,) = self.s.actions("t01")
        self.assertEqual((a["type"], a["id"], a["request"]["path"], a["request"]["method"], a["strikes"]),
                         ("warning", action_id("m-1|9|t01"), "/plaza/api/me", "GET", 1))
        self.assertEqual(len(a["id"]), 14)
        self.assertFalse(self.s.ack("t02", a["id"]))           # not its warning
        self.assertTrue(self.s.ack("t01", a["id"]))
        self.assertEqual((self.s.actions("t01"), self.s.standing("t01")["acked"]), ([], True))
        self.assertEqual(self.s.actions("t02"), [])


class HttpTest(unittest.TestCase):
    """Through HTTP, with test_server's public sheet: t09 asks 20 for LAT-06 and t07 bids 20."""
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call
    connect, event, mid = DA.RoutesTest.connect, DA.RoutesTest.event, DA.RoutesTest.mid

    def elsewhere(self, moved=False):
        self.event(id=3, tick=81, type="offer.listed", payload={"offer": {
            "id": 77, "maker": "t09", "to": "t07", "venue": "rastro", "give": {"cards": ["LAT-06"]},
            "want": {"cash": 21}, "created_tick": 81}})
        if moved:                                              # cancelled there and posted here before it closed
            self.event(id=4, tick=82, type="offer.cancelled", payload={"offer": 77, "venue": "rastro"})
            self.event(id=5, tick=82, type="offer.listed", payload={"offer": {
                "id": 78, "maker": "t09", "to": "t07", "venue": "v07", "give": {"cards": ["LAT-06"]},
                "want": {"cash": 21}, "created_tick": 82}})
        self.event(id=6, tick=83, type="settlement", payload={
            "settlement": 9, "venue": "v07" if moved else "rastro", "price": 21, "parties": ["t09", "t07"],
            "items": [{"ref": "LAT-06", "frm": "t09", "to": "t07"}]})
        self.board.rebuild()

    def test_a_matched_trade_closed_elsewhere_warns_its_maker(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        mid = self.mid()
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t9)[1]["standing"]["strikes"], 0)
        self.elsewhere()
        me = self.call("GET", "/plaza/api/me", headers=t9)[1]
        self.assertEqual((me["standing"]["strikes"], me["standing"]["limit"], me["standing"]["banned"]), (1, 2, False))
        self.assertEqual(me["standing"]["last"], {"match": mid, "card": "LAT-06", "venue": "rastro", "tick": 83,
                                                 "with": "t07", "seller": "t09", "buyer": "t07", "name": "La Chulapa"})
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t7)[1]["standing"]["strikes"], 0)   # it only accepted
        self.assertEqual(self.call("GET", "/plaza/api/status", headers=t9)[1]["standing"]["strikes"], 1)
        self.assertNotIn("standing", self.call("GET", "/plaza/api/status")[1])       # nobody else's business
        nxt = self.call("GET", "/plaza/api/agent/next", headers=t9)[1]
        self.assertEqual((nxt["standing"]["strikes"], nxt["actions"][0]["type"]), (1, "warning"))
        self.assertEqual(self.call("POST", "/plaza/api/agent/ack", {"id": nxt["actions"][0]["id"], "status": "done"},
                                   t9)[0], 200)
        nxt = self.call("GET", "/plaza/api/agent/next", headers=t9)[1]
        self.assertNotIn("warning", [a["type"] for a in nxt["actions"]])
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=t9)[0], 200)   # warned, not out
        self.board.rebuild()                                   # and the same closing never counts twice
        self.assertEqual(self.board.strikes.standing("t09")["strikes"], 1)
        act = self.call("GET", "/plaza/api/me/activity", headers=t9)[1]
        self.assertIn("Warning 1 of 2", json.dumps(act))
        self.assertNotIn("Warning", json.dumps(self.call("GET", "/plaza/api/floor")[1]))   # never in public

    def test_an_offer_moved_to_our_venue_is_no_strike(self):
        self.connect("t07"), self.connect("t09")
        self.elsewhere(moved=True)
        self.assertEqual(self.board.strikes.view()["teams"], [])
        self.assertEqual(self.board.deals.counts()["settled"], 1)

    def test_a_team_that_never_connected_is_not_struck(self):
        self.connect("t07")                                    # t09 trades through the game's API only
        self.elsewhere()
        self.assertEqual(self.board.strikes.view()["teams"], [])
        self.assertEqual(self.board.strikes.view()["log"][0]["kind"], "skipped")

    def test_banned_is_out_of_every_route_but_the_two_that_explain_it(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        mid = self.mid()
        self.elsewhere()
        self.board.strikes.record("m-0000000001|2", match="m-0000000001", ref="LAT-03", venue="v01", tick=90,
                                  parties=["t09", "t08"], maker="t09", verified={"t09"}, saw={"t09"})
        self.board.rebuild()
        for method, path, body in (("GET", "/plaza/api/me/cards", None), ("GET", "/plaza/api/agent/next", None),
                                   ("GET", "/plaza/api/me/trades", None), ("GET", "/plaza/api/me/settings", None),
                                   ("GET", "/plaza/api/me/activity", None), ("GET", "/plaza/api/agent/cards", None),
                                   ("GET", "/plaza/api/me/suggestions", None),
                                   ("PUT", "/plaza/api/team/t09", {"wants": ["LAT-03"]}),
                                   ("POST", "/plaza/api/me/cards", {"op": "add", "list": "wants", "ref": "LAT-03"}),
                                   ("POST", "/plaza/api/me/card/LAT-03", {"max": 9}),
                                   ("POST", "/plaza/api/me/settings", {"paused": True}),
                                   ("POST", "/plaza/api/suggestions", {"text": "let me back in please"}),
                                   ("POST", "/plaza/api/agent/ack", {"id": "a-000000000000", "status": "done"}),
                                   ("POST", "/plaza/api/floor", {"kind": "want", "ref": "LAT-03", "price": 9}),
                                   ("POST", f"/plaza/api/me/trade/{mid}", {"order": "pass"}),
                                   ("POST", f"/plaza/api/match/{mid}/message", {"action": "pass"})):
            st, out, _ = self.call(method, path, body, t9)
            self.assertEqual((st, out.get("error")), (403, "banned"), path)
        st, me, _ = self.call("GET", "/plaza/api/me", headers=t9)
        self.assertEqual((st, me["standing"]["banned"], me["standing"]["strikes"]), (200, True, 2))
        self.assertIn("Ask Team 10 in person", me["standing"]["message"])
        self.assertTrue(self.call("GET", "/plaza/api/status", headers=t9)[1]["standing"]["banned"])
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=t7)[0], 200)   # the other team is untouched
        self.assertEqual(self.call("GET", "/plaza/api/market")[0], 200)                 # and the public board is public
        live = self.call("GET", "/plaza/api/matches")[1]["matches"]
        self.assertFalse([m for m in live if "t09" in (m["seller"], m["buyer"])])       # in no match, new or live

    def test_our_panel_sees_the_evidence_and_can_forgive_lift_and_ban(self):
        t9 = (self.connect("t07"), self.connect("t09"))[1]
        self.elsewhere()
        st, teams, _ = self.call("GET", "/plaza/admin/api/teams", headers=ADMIN)
        row = next(t for t in teams["teams"] if t["team"] == "t09")
        self.assertEqual((st, row["standing"]), (200, {"strikes": 1, "limit": 2, "banned": False}))
        ev = teams["strikes"]["teams"][0]["evidence"][0]
        self.assertEqual((ev["match"], ev["card"], ev["venue"], ev["tick"], ev["settlement"], ev["offer"], ev["role"]),
                         (self.board.strikes.standing("t09")["last"]["match"], "LAT-06", "rastro", 83, 9, 77, "posted"))
        perf = self.call("GET", "/plaza/admin/api/performance", headers=ADMIN)[1]
        self.assertEqual((perf["strikes"]["warned"], perf["alerts"][0]["kind"]), (1, "strike"))
        act = lambda body: self.call("POST", "/plaza/admin/api/action", body, ADMIN)    # noqa: E731
        self.assertEqual(act({"action": "forgive", "team": "t09"})[1]["standing"]["strikes"], 0)
        self.assertEqual(act({"action": "forgive", "team": "t09"})[0], 404)
        self.assertEqual(act({"action": "ban", "team": "t09", "reason": "by hand"})[1]["standing"]["banned"], True)
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=t9)[1]["error"], "banned")
        self.assertEqual(act({"action": "unban", "team": "t09"})[1]["standing"]["banned"], False)
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=t9)[0], 200)
        self.assertEqual(act({"action": "strikes", "limit": 3})[1]["strikes"], {"on": True, "limit": 3, "accepter": False})
        self.assertEqual(act({"action": "strikes", "on": False})[1]["strikes"]["on"], False)
        for body in ({"action": "ban", "team": "t10"}, {"action": "ban", "team": "zz"}, {"action": "unban", "team": "t07"},
                     {"action": "strikes"}, {"action": "strikes", "limit": 99}, {"action": "forgive", "team": "t09", "x": 1}):
            self.assertIn(act(body)[0], (400, 404, 409), body)
        for body in ({"action": "ban", "team": "t09"}, {"action": "strikes", "on": False}):   # never from a team
            self.assertEqual(self.call("POST", "/plaza/admin/api/action", body, t9)[0], 404)


if __name__ == "__main__":
    unittest.main()
