"""What a match shows to whom: its two teams read the terms; everybody else reads who, which card and the state."""
import json
import unittest

from bazaar.plaza.tests import test_server as T
from bazaar.plaza.tests.test_connect_deals import FlowTest

SECRET = ("why", "recipe", "thread", "last_message", "suggested", "agreed", "saves", "rastro_fee", "alternatives",
          "last_of_page", "priority", "score", "price_by", "reported_offer")


class WhoReadsWhatTest(unittest.TestCase):
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call
    connect, event = FlowTest.connect, FlowTest.event

    def token(self, team):
        return {"X-Plaza-Token": self.connect(team)[1]}

    def rows(self, who, mid):
        """Every public read that carries the match, as `who` gets it."""
        get = lambda path: self.call("GET", path, headers=who)[1]   # noqa: E731
        return [get("/plaza/api/matches")["matches"][0], get(f"/plaza/api/match/{mid}"),
                get("/plaza/api/team/t07")["trades"][0], get("/plaza/api/team/t09")["matches"][0],
                get("/plaza/api/offers?team=t07")["trades"][0], get("/plaza/api/card/LAT-06")["matches"][0]]

    def test_terms_are_for_the_two_teams_until_the_game_settles_them(self):
        t7, t9, t8 = self.token("t07"), self.token("t09"), self.token("t08")
        mid = self.call("GET", "/plaza/api/matches")[1]["matches"][0]["id"]
        self.call("POST", f"/plaza/api/match/{mid}/message", {"action": "counter", "price": 31, "text": "thirty-one"}, t7)
        for who in (None, t8):
            for row in self.rows(who, mid):
                self.assertEqual((row["seller"], row["buyer"], row["ref"], row["state"], row["price"]),
                                 ("t09", "t07", "LAT-06", "proposed", None))
                self.assertEqual([k for k in SECRET if k in row], [], row)
                self.assertNotIn("31", json.dumps(row))
            raw = json.dumps(self.call("GET", "/plaza/api/floor", headers=who)[1])
            self.assertNotIn("thirty-one", raw)
            self.assertIn(mid, raw)                                # that it happened is public
            possible = self.call("GET", "/plaza/api/card/LAT-06", headers=who)[1]["possible_matches"]
            self.assertEqual([(p["price"], "finishes_page" in p) for p in possible], [(None, False)])
        for who in (t7, t9):
            for row in self.rows(who, mid):
                self.assertEqual((row["price"], "recipe" in row), (31, True))
            self.assertIn("thirty-one", json.dumps(self.call("GET", "/plaza/api/floor", headers=who)[1]))
        self.assertEqual(len(self.call("GET", f"/plaza/api/match/{mid}", headers=t9)[1]["thread"]), 1)

    def test_that_a_card_ends_a_page_is_told_to_its_buyer_alone(self):
        t7, t9 = self.token("t07"), self.token("t09")
        mid = self.call("GET", "/plaza/api/matches")[1]["matches"][0]["id"]
        for who, sees in ((None, False), (t9, False), (t7, True)):
            team = self.call("GET", "/plaza/api/team/t07", headers=who)[1]
            card = self.call("GET", "/plaza/api/card/LAT-06", headers=who)[1]
            m = self.call("GET", f"/plaza/api/match/{mid}", headers=who)[1]
            self.assertEqual(["finishes_page" in e for e in team["looking_for"]], [sees])
            self.assertEqual(["finishes_page" in k for k in card["seekers"]], [sees])
            self.assertEqual("last_of_page" in m, sees)
            self.assertNotIn("last card of its page", json.dumps([team, card, m]))
        self.assertTrue(self.call("GET", "/plaza/api/me", headers=t7)[1]["home"]["looking_for"][0]["finishes_page"])

    def test_a_settled_card_takes_its_limits_and_its_place_on_the_sheet_with_it(self):
        """The second cold test: after the duplicate was sold, `min 20, value 18` stayed on the last copy."""
        t7, t9 = self.token("t07"), self.token("t09")
        self.assertEqual(self.call("PUT", "/plaza/api/team/t09", {"spares": [{"ref": "LAT-06", "min": 15, "value": 18}],
                                                                  "wants": [{"ref": "LAT-03", "max": 9}]}, t9)[0], 200)
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 25}]}, t7)[0], 200)
        self.board.vault.put("t09", "LAT-06", {"min": 16}, tick=79)                # moved a moment ago: cooling
        self.event(id=3, tick=82, type="settlement", payload={
            "settlement": 1054, "kind": "trade", "venue": "v07", "price": 20, "parties": ["t09", "t07"], "fee": 0,
            "items": [{"ref": "LAT-06", "frm": "t09", "to": "t07"}]})
        self.call("GET", "/plaza/api/matches")
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t9)[1]["limits"], {"LAT-03": {"max": 9}})
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t7)[1]["limits"], {})
        self.assertEqual(self.board.store.sheet("t09")["effective"]["spares"], [])
        self.assertEqual(self.board.store.sheet("t07")["effective"]["wants"], [])
        self.board.vault.put("t09", "LAT-06", {"min": 60}, tick=83)                # the last copy: a new card, no cooldown
        self.assertEqual(self.board.vault.get("t09")["LAT-06"], {"min": 60})

    def test_what_the_second_cold_agent_had_to_guess(self):
        t7 = self.token("t07")
        nxt = self.call("GET", "/plaza/api/agent/next", headers=t7)[1]
        self.assertIs(nxt["verified"], True)                           # always there, true or false
        self.assertLessEqual(nxt["poll_after_s"], 15)                  # something waits: within a tick
        raw = {"X-Plaza-Token": self.connect("t08", prove=False)[1]}
        self.assertIs(self.call("GET", "/plaza/api/agent/next", headers=raw)[1]["verified"], False)
        self.assertIs(self.call("GET", "/plaza/api/me", headers=t7)[1]["ready"], True)
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 25, "min": 3}]}, t7)
        self.assertEqual(st, 400)
        self.assertTrue("min" in out["message"] and "max" in out["message"] and "value" in out["message"], out)
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "price": 9}]}, t7)
        self.assertTrue(st == 400 and "price" in out["message"] and "max" in out["message"], out)
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {"wishes": []}, t7)
        self.assertTrue(st == 400 and "wishes" in out["message"] and "wants" in out["message"], out)
        st, out, _ = self.call("POST", "/plaza/api/me/card/LAT-06", {"maxx": 5}, t7)
        self.assertTrue(st == 400 and "maxx" in out["message"] and "max" in out["message"], out)
        # the game hands out 17.5 and 2.5: taken, and rounded in the team's favour
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {
            "wants": [{"ref": "LAT-06", "max": 17.5, "value": 2.5}], "spares": [{"ref": "LAT-03", "min": 17.5}]}, t7)[0], 200)
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t7)[1]["limits"],
                         {"LAT-06": {"max": 17, "value": 3}, "LAT-03": {"min": 18}})


if __name__ == "__main__":
    unittest.main()
