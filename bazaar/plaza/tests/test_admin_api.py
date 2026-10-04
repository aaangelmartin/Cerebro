"""Our panel: only behind the admin check, every screen answers, and no private limit is ever in an answer."""
import json
import time
import unittest

from bazaar.plaza.tests import test_deals_api as DA
from bazaar.plaza.tests import test_server as T

ADMIN = {"X-Plaza-Admin": "test-admin-token"}
ROUTES = ("status", "performance", "trades", "teams", "suggestions", "venue")
SECRETS = ("1333", "1771", "1991")


class AdminTest(unittest.TestCase):
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call
    connect, event, mid = DA.RoutesTest.connect, DA.RoutesTest.event, DA.RoutesTest.mid

    def game(self, me=None, venues=None):
        latest = self.record / "latest"
        if me is not None:
            (latest / "me.json").write_text(json.dumps(me))
        if venues is not None:
            (latest / "venues.json").write_text(json.dumps({"tick": 80, "venues": venues}))

    def test_the_public_never_learns_the_panel_exists(self):
        t7 = self.connect("t07")
        for name in ROUTES:
            path = f"/plaza/admin/api/{name}"
            self.assertEqual(self.call("GET", path)[0], 404, path)
            self.assertEqual(self.call("GET", path, headers=t7)[0], 404, path)              # a team's token is not ours
            self.assertEqual(self.call("GET", path, headers={"X-Plaza-Admin": "nope"})[0], 404, path)
            self.assertEqual(self.call("GET", path, headers={**ADMIN, "CF-Ray": "1"})[0], 404, path)   # never from outside
            self.assertEqual(self.call("GET", path, headers=ADMIN)[0], 200, path)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "suggestion", "id": "s-0001",
                                                                     "status": "done"}, t7)[0], 404)
        self.assertEqual(self.call("GET", "/plaza/admin/api/nope", headers=ADMIN)[0], 404)

    def test_status_names_every_process(self):
        (self.live / "recorder_status.json").write_text(json.dumps({"updated": time.time(), "tick": 77}))
        (self.live / "broker_status.json").write_text(json.dumps({"updated": time.time() - 4000, "tick": 70}))
        st, out, _ = self.call("GET", "/plaza/admin/api/status", headers=ADMIN)
        procs = {p["id"]: p for p in out["processes"]}
        self.assertEqual((st, list(procs)), (200, ["server", "tunnel", "matchmaker", "recorder", "venue", "broker"]))
        self.assertEqual((procs["server"]["state"], procs["recorder"]["state"], procs["broker"]["state"],
                          procs["tunnel"]["state"]), ("on", "on", "stale", "off"))
        self.assertIn("1 live match,", procs["matchmaker"]["detail"])
        self.assertEqual((out["enabled"], out["paused"]), (True, False))
        self.call("POST", "/plaza/admin/api/action", {"action": "pause"}, ADMIN)
        out = self.call("GET", "/plaza/admin/api/status", headers=ADMIN)[1]
        self.assertEqual((out["paused"], {p["id"]: p["state"] for p in out["processes"]}["matchmaker"]), (True, "paused"))

    def test_trades_by_state_and_team_with_overlap_yes_or_no(self):
        self.connect("t07")
        st, out, _ = self.call("GET", "/plaza/admin/api/trades", headers=ADMIN)
        self.assertEqual((st, out["total"], out["counts"]["proposed"]), (200, 1, 1))
        row = out["trades"][0]
        self.assertEqual((row["seller"], row["buyer"], row["state"], row["overlap"], row["stalled"], row["basis"]),
                         ("t09", "t07", "proposed", None, False, "public"))
        self.assertEqual([s["team"] for s in row["sides"]], ["t09", "t07"])
        self.assertEqual(self.call("GET", "/plaza/admin/api/trades?state=settled", headers=ADMIN)[1]["total"], 0)
        self.assertEqual(self.call("GET", "/plaza/admin/api/trades?state=live&team=t09", headers=ADMIN)[1]["total"], 1)
        self.assertEqual(self.call("GET", "/plaza/admin/api/trades?team=t08", headers=ADMIN)[1]["total"], 0)
        self.assertEqual(self.call("GET", "/plaza/admin/api/trades?state=x%27;drop", headers=ADMIN)[0], 400)
        self.assertEqual(self.call("GET", "/plaza/admin/api/trades?team=zz", headers=ADMIN)[0], 400)
        self.event(id=3, tick=82, type="settlement", payload={
            "settlement": 9, "venue": "rastro", "price": 21, "parties": ["t09", "t07"],
            "items": [{"ref": "LAT-06", "frm": "t09", "to": "t07"}]})
        out = self.call("GET", "/plaza/admin/api/trades?state=done", headers=ADMIN)[1]
        self.assertEqual([(t["state"], t["settled_venue"]) for t in out["trades"]], [("settled_elsewhere", "rastro")])
        self.assertEqual([(c["state"], c["venue"]) for c in out["closed"]], [("settled_elsewhere", "rastro")])

    def test_performance_puts_the_games_count_next_to_ours(self):
        self.game(me={"score": {"market": 12.5, "mm_points": 7.6, "rank": 1, "score": 37.58},
                      "venue": {"venue": "v07", "trades": 11, "volume": 100, "traders": 8, "pairs": 8, "fee_bps": 0,
                                "status": "open", "value_created": 59.2}},
                  venues=[{"venue": "v07", "name": "Team 10", "owner": "t10", "trades": 11, "volume": 100, "traders": 8,
                           "pairs": 8, "fee_bps": 0, "status": "open"},
                          {"venue": "v01", "name": "Mercado Team 6", "owner": "t06", "trades": 3, "volume": 101,
                           "traders": 3, "pairs": 2, "fee_bps": 0}])
        st, p, _ = self.call("GET", "/plaza/admin/api/performance", headers=ADMIN)
        self.assertEqual(st, 200)
        self.assertEqual((p["score"]["market"], p["score"]["mm_points"], p["venue"]["trades"], p["venue"]["value_created"]),
                         (12.5, 7.6, 11, 59.2))
        self.assertEqual((p["feed"]["venue_deals"], p["ours"]["settled"], p["ours"]["settled_elsewhere"]), (1, 0, 0))
        kinds = [a["kind"] for a in p["alerts"]]
        self.assertIn("count", kinds)                              # the game says 11, our feed saw 1: say so
        self.assertIn("broker", kinds)                             # no broker status: public offers are not paired
        self.assertIn("no_agents", kinds)
        self.assertEqual(p["alert"], p["alerts"][0]["text"])
        self.assertEqual([(v["venue"], v["ours"]) for v in p["venues"]], [("v07", True), ("v01", False)])
        self.assertEqual(set(p["funnel"]), {"proposed", "offer_on_v07", "accepted", "settled", "passed", "expired",
                                            "settled_elsewhere"})
        self.connect("t07")
        self.event(id=3, tick=82, type="settlement", payload={
            "settlement": 9, "venue": "rastro", "price": 21, "parties": ["t09", "t07"],
            "items": [{"ref": "LAT-06", "frm": "t09", "to": "t07"}]})
        p = self.call("GET", "/plaza/admin/api/performance", headers=ADMIN)[1]
        self.assertEqual((p["ours"]["settled_elsewhere"], p["funnel"]["settled_elsewhere"]), (1, 1))
        self.assertEqual([(x["seller"], x["buyer"], x["ref"], x["venue"]) for x in p["lost"]], [("t09", "t07", "LAT-06", "rastro")])
        self.assertIn("lost", [a["kind"] for a in p["alerts"]])
        self.assertNotIn("no_agents", [a["kind"] for a in p["alerts"]])
        self.assertEqual(p["feed"]["by_venue"], {"v07": 1, "rastro": 1})
        self.assertEqual(p["feed"]["share"], 0.5)
        self.assertEqual(p["per_tick"], [{"tick": 82, "settled": 0, "elsewhere": 1, "volume": 0}])

    def test_teams_venue_and_suggestions(self):
        self.connect("t07")
        st, out, _ = self.call("GET", "/plaza/admin/api/teams", headers=ADMIN)
        self.assertEqual((st, len(out["teams"]), out["agents"]), (200, 17, 1))
        row = next(t for t in out["teams"] if t["team"] == "t07")
        self.assertEqual((row["agent"], row["limits_set"], row["paused"], row["matches"]), (True, False, False, 1))
        self.game(me={"venue": {"venue": "v07", "name": "Team 10 · fair broker, 0 fee", "fee_bps": 0, "status": "open"}},
                  venues=[{"venue": "v01", "name": "Mercado Team 6", "owner": "t06", "trades": 3}])
        st, v, _ = self.call("GET", "/plaza/admin/api/venue", headers=ADMIN)
        self.assertEqual((st, v["venue"]["venue"], [o["venue"] for o in v["others"]]), (200, "v07", ["v01"]))
        self.assertIn("read_only", v)
        st, s, _ = self.call("GET", "/plaza/admin/api/suggestions", headers=ADMIN)
        self.assertEqual((st, s["suggestions"], set(s["counts"])), (200, [], {"open", "planned", "done", "dismissed"}))
        for body in ({"action": "suggestion"}, {"action": "suggestion", "id": 4, "status": "done"},
                     {"action": "suggestion", "id": "s-0001"}, {"action": "suggestion", "id": "s-0001", "x": 1, "status": "done"}):
            self.assertEqual(self.call("POST", "/plaza/admin/api/action", body, ADMIN)[0], 400, body)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "suggestion", "id": "s-9999", "status": "done"},
                                   ADMIN)[0], 404)

    def test_no_private_limit_in_any_answer_of_the_panel(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        with self.board.vault.lock:                                  # limits that overlap, set by the two teams
            self.board.vault.data["t09"] = {"LAT-06": {"min": 1333, "value": 1501}}
            self.board.vault.data["t07"] = {"LAT-06": {"max": 1771, "value": 1991}}
        self.board.rebuild()
        blob = ""
        for name in ROUTES + ("overview", "matchmaker", "activity"):
            st, out, _ = self.call("GET", f"/plaza/admin/api/{name}", headers=ADMIN)
            self.assertEqual(st, 200, name)
            blob += json.dumps(out)
        for path, cred in (("/plaza/api/me/trades", t7), ("/plaza/api/me/trades", t9), ("/plaza/api/market", None),
                           ("/plaza/api/card/LAT-06", None), ("/plaza/api/stats", None), ("/plaza/api/agent/next", t9)):
            blob += json.dumps(self.call("GET", path, headers=cred or {})[1])
        mine = json.dumps(self.call("GET", "/plaza/api/me/trades", headers=t7)[1]) + \
            json.dumps(self.call("GET", "/plaza/api/agent/next", headers=t7)[1])
        self.assertNotIn("1333", mine)                               # the seller's floor is not in the buyer's answers
        for secret in ("1333", "1991", "1501"):
            self.assertNotIn(secret, blob, secret)
        trades = self.call("GET", "/plaza/admin/api/trades", headers=ADMIN)[1]["trades"]
        self.assertEqual((trades[0]["overlap"], trades[0]["basis"]), (True, "limits"))    # yes or no, and a word
        self.assertTrue(1333 <= trades[0]["price"] <= 1771)
        for path in self.live.rglob("*"):
            if path.is_file():
                raw = path.read_text(errors="ignore")
                for secret in SECRETS:
                    self.assertNotIn(secret, raw, (path.name, secret))


if __name__ == "__main__":
    unittest.main()
