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


if __name__ == "__main__":
    unittest.main()
