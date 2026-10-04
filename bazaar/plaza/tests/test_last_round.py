"""What the third cold test and the third review found: each team reads its own view, dates and numbers are right,
and what a team told us it holds follows the card."""
import json
import unittest

from bazaar.plaza.tests import test_deals_api as DA
from bazaar.plaza.tests import test_server as T


class LastRoundTest(unittest.TestCase):
    """test_server's public sheet: t09 asks 20 for LAT-06 and t07 bids 20."""
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call
    connect, event, mid = DA.RoutesTest.connect, DA.RoutesTest.event, DA.RoutesTest.mid

    def settle(self, venue="v07"):
        self.event(id=3, tick=81, type="offer.listed", payload={"offer": {
            "id": 77, "maker": "t07", "to": "t09", "venue": venue, "give": {"cash": 20},
            "want": {"cards": ["LAT-06"]}, "created_tick": 81}})
        self.event(id=6, tick=83, type="settlement", payload={
            "settlement": 1127, "venue": venue, "price": 20, "parties": ["t07", "t09"],
            "items": [{"ref": "LAT-06", "frm": "t09", "to": "t07"}]})
        self.board.rebuild()

    def test_that_a_card_ends_the_buyers_page_is_never_told_to_the_seller(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        mid = self.mid()
        self.board.deals.matches[mid]["last_of_page"] = True
        self.board.stale()
        for path, pick in (("/plaza/api/me/trades", lambda o: o["trades"][0]), (f"/plaza/api/match/{mid}", lambda o: o),
                           ("/plaza/api/me", lambda o: o["home"]["matches"][0])):
            seller, buyer = pick(self.call("GET", path, headers=t9)[1]), pick(self.call("GET", path, headers=t7)[1])
            for key in ("last_of_page", "priority", "score"):
                self.assertNotIn(key, seller, (path, key))
            self.assertIs(buyer.get("last_of_page"), True, path)
        said = self.call("POST", f"/plaza/api/match/{mid}/message", {"text": "hello"}, t9)[1]["match"]
        self.assertNotIn("last_of_page", said)                 # nor in the answer to what the seller says
        self.assertNotIn("page", json.dumps(self.call("GET", "/plaza/api/agent/next", headers=t9)[1]).lower())

    def test_a_settled_match_is_not_veiled_and_keeps_the_games_settlement(self):
        self.connect("t07"), self.connect("t09")
        mid = self.mid()
        pub = self.call("GET", f"/plaza/api/match/{mid}")[1]
        self.assertEqual((pub["price"], pub["veiled"]), (None, True))
        self.settle()
        pub = self.call("GET", f"/plaza/api/match/{mid}")[1]
        self.assertEqual((pub["state"], pub["price"], pub["veiled"], pub["settlement"], pub["settled_venue"]),
                         ("settled", 20, False, 1127, "v07"))

    def test_messages_carry_the_tick_of_now_and_are_numbered_per_thread(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        mid = self.mid()
        self.board.deals.now = lambda: 1518                    # the game clock is past the last tick the feed showed
        a = self.call("POST", f"/plaza/api/match/{mid}/message", {"action": "counter", "price": 21}, t9)[1]
        b = self.call("POST", f"/plaza/api/match/{mid}/message", {"text": "fine"}, t7)[1]
        self.assertEqual((a["posted"], b["posted"]), (1, 2))
        thread = b["match"]["thread"]
        self.assertEqual([(m["n"], m["tick"]) for m in thread], [(1, 1518), (2, 1518)])
        other = self.board.deals.force({**{k: v for k, v in self.board.deals.get(mid).items()
                                           if k not in ("messages", "history")}, "id": "m-00000000ab", "price": 20})
        self.board.deals.matches[other["id"]]["forced"] = False
        c = self.board.deals.message(other["id"], "t07", True, {"text": "another thread"})[1]
        self.assertEqual(c["msg"], 1)                          # every thread starts at 1
        self.board.deals.now = lambda: 3                       # a clock behind the feed never dates anything back
        d = self.board.deals.message(mid, "t07", True, {"text": "still here"})[1]
        self.assertEqual(d["tick"], self.board.deals.tick)

    def test_what_a_team_holds_follows_the_card(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        self.assertEqual(self.call("PUT", "/plaza/api/team/t09", {"for_sale": [{"ref": "LAT-06", "price": 20}],
                                                                  "have": ["LAT-06", "LAT-03"]}, t9)[0], 200)
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-06"], "have": ["LAT-03"]}, t7)[0], 200)
        self.board.rebuild()
        self.settle()
        self.assertEqual(sorted(self.call("GET", "/plaza/api/me", headers=t7)[1]["owned"]), ["LAT-03", "LAT-06"])
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t9)[1]["owned"], ["LAT-03"])     # its only copy left

    def test_a_duplicate_sold_stays_in_the_sellers_hand(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        self.call("PUT", "/plaza/api/team/t09", {"spares": [{"ref": "LAT-06"}], "have": ["LAT-06"]}, t9)
        self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-06"], "have": []}, t7)
        self.board.rebuild()
        self.settle()
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t9)[1]["owned"], ["LAT-06"])     # one copy is left
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=t7)[1]["owned"], ["LAT-06"])

    def test_the_public_list_of_matches_is_not_in_order_of_priority(self):
        self.connect("t07"), self.connect("t09")
        mid = self.mid()
        rec = self.board.deals.get(mid)
        for i, (prio, tick) in enumerate(((1, 5), (3, 9))):     # the one that ends a page is the older one
            self.board.snap["matches"].append({**self.board.match_view(rec, (set(), set())), "id": f"m-00000000a{i}",
                                               "priority": prio, "state_tick": tick})
        self.board.snap["matches"].sort(key=lambda m: m.get("priority", 4))
        ids = [m["id"] for m in self.call("GET", "/plaza/api/matches")[1]["matches"]]
        self.assertEqual(ids[0], "m-00000000a1")               # newest first, whatever its priority

    def test_ticks_that_start_again_do_not_open_the_cooldown(self):
        v = self.board.vault
        v.put("t07", "LAT-06", {"max": 30}, tick=500)
        v.put("t07", "LAT-06", {"max": 31}, tick=530)
        self.assertTrue(v.cooling("t07", "LAT-06", {"max": 32}, 3))     # the game's ticks went back to 3 just now

    def test_a_room_can_start_connecting_many_times_from_one_address(self):
        from bazaar.plaza import connect
        self.assertGreaterEqual(connect.STARTS_PER_CLIENT, 2000)        # twenty teams, pages reloaded, agents retried

    def test_no_credential_at_all_is_told_which_one_to_send(self):
        for path in ("/plaza/api/me/trades", "/plaza/api/me/cards", "/plaza/api/me"):
            st, out, _ = self.call("GET", path)
            self.assertEqual((st, out["error"]), (401, "bad_token"), path)
            self.assertIn("X-Plaza-Token", out["message"])


if __name__ == "__main__":
    unittest.main()
