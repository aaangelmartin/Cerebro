"""Auctions: public bids, a private reserve, and an awarded lot that closes on v07 like any match."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from bazaar.plaza import lots as L
from bazaar.plaza.store import PlazaError
from bazaar.plaza.tests import test_deals_api as DA
from bazaar.plaza.tests import test_server as T

CARD = {"name": "Museo", "rarity": "rare"}                    # the floor of a rare is 40
ADMIN = {"X-Plaza-Admin": "test-admin-token"}


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "private").mkdir()
        self.lots = L.Lots(self.root / "plaza_lots.json", self.root / "private", os.urandom(32))
        self.awards, self.defaults, self.expired, self.matches = [], [], [], {}

    def tearDown(self):
        self.dir.cleanup()

    def award(self, lot, bid):
        mid = f"m-{len(self.awards):010x}"
        self.awards.append((lot["id"], bid["team"], bid["price"]))
        self.matches[mid] = {"state": "proposed", "messages": []}
        return mid

    def sync(self, tick, auto=True):
        return self.lots.sync(tick, self.award, self.matches.get, self.expired.append,
                              lambda lot, bid: self.defaults.append((lot["id"], bid["team"])), lambda team: auto)

    def lot(self, tick=100, **body):
        return self.lots.create("t04", {"card": "SAL-10", **body}, CARD, {"SAL-10"}, tick)

    def test_a_lot_needs_a_card_the_team_holds_and_sane_numbers(self):
        for body, owned in (({"card": "SAL-10"}, set()), ({"card": "SAL-10", "start": 39}, {"SAL-10"}),      # under the floor
                            ({"card": "SAL-10", "start": 50, "reserve": 45}, {"SAL-10"}), ({"card": "SAL-10", "ticks": 241}, {"SAL-10"}),
                            ({"card": "SAL-10", "ticks": 3}, {"SAL-10"}), ({"card": "SAL-10", "price": 5}, {"SAL-10"}),
                            ({"card": "nope"}, {"SAL-10"}), ({}, {"SAL-10"}), ([1], {"SAL-10"}), ({"card": "SAL-10", "start": True}, {"SAL-10"})):
            self.assertRaises(PlazaError, self.lots.create, "t04", body, CARD, owned, 100)
        self.assertRaises(PlazaError, self.lots.create, "t10", {"card": "SAL-10"}, CARD, {"SAL-10"}, 100)     # the host never sells
        lot = self.lot()
        self.assertEqual((lot["state"], lot["start"], lot["ends_tick"], lot["next_bid"], lot["bids"]), ("open", 40, 140, 40, []))
        self.assertTrue(L.ID_RX.fullmatch(lot["id"]))
        again = self.lot(start=60)
        self.assertEqual((again["id"], again["repeated"], again["start"]), (lot["id"], True, 40))             # one lot per card and team
        for i in range(1, L.LOTS_PER_TEAM):
            self.lots.create("t04", {"card": f"SAL-0{i}"}, CARD, {f"SAL-0{i}"}, 100)
        self.assertRaises(PlazaError, self.lots.create, "t04", {"card": "SAL-09"}, CARD, {"SAL-09"}, 100)

    def test_bids_rise_by_the_step_and_some_teams_never_bid(self):
        lot = self.lot()["id"]
        for team, price in (("t04", 50), ("t10", 50), ("t05", 39), ("t05", 2001), ("t05", 45.5)):
            self.assertRaises(PlazaError, self.lots.bid, team, lot, {"price": price}, 101)
        self.assertRaises(PlazaError, self.lots.bid, "t05", lot, {"price": 50, "note": "x"}, 101)
        self.assertRaises(PlazaError, self.lots.bid, "t05", "l-00000000", {"price": 50}, 101)
        out = self.lots.bid("t05", lot, {"price": 40}, 101)
        self.assertEqual((out["best_bid"], out["best_bidder"], out["next_bid"], out["you"]["winning"]), (40, "t05", 45, True))
        self.assertTrue(self.lots.bid("t05", lot, {"price": 40}, 102)["repeated"])                           # the same bid: nothing new
        self.assertRaises(PlazaError, self.lots.bid, "t06", lot, {"price": 44}, 102)                          # under the step
        out = self.lots.bid("t06", lot, {"price": 45}, 102)
        self.assertEqual([(b["team"], b["price"], b["state"]) for b in out["bids"]], [("t05", 40, "outbid"), ("t06", 45, "live")])
        self.assertRaises(PlazaError, self.lots.bid, "t05", lot, {"price": 60}, 140)                          # over
        self.assertEqual(L.step(19), 1)
        self.assertEqual(L.step(20), 5)

    def test_a_late_bid_moves_the_end_a_few_times_only(self):
        lot = self.lot()["id"]
        price, ends = 40, []
        for i in range(5):
            tick = self.lots.lots[lot]["ends_tick"] - 1
            self.lots.bid(f"t0{5 + i % 2}", lot, {"price": price}, tick)
            price += 5
            ends.append(self.lots.lots[lot]["ends_tick"])
        self.assertEqual(ends, [144, 148, 152, 152, 152])

    def test_the_reserve_is_in_no_answer_and_in_no_file_under_live(self):
        lot = self.lot(start=40, reserve=1234)["id"]
        self.lots.bid("t05", lot, {"price": 45}, 101)
        for text in (json.dumps(self.lots.listing()), json.dumps(self.lots.view(self.lots.lots[lot])),
                     json.dumps(self.lots.view(self.lots.lots[lot], viewer="t05")), json.dumps(self.lots.actions("t06", {"SAL-10"})),
                     (self.root / "plaza_lots.json").read_text()):
            self.assertNotIn("1234", text)
            self.assertNotIn("reserve", text.replace("reserve_set", ""))
        self.assertNotIn(b"1234", (self.root / "private" / "lots.bin").read_bytes())                          # sealed, too
        self.assertEqual(self.lots.view(self.lots.lots[lot], viewer="t04")["you"], {"role": "seller", "reserve_set": True, "reserve": 1234})
        again = L.Lots(self.root / "plaza_lots.json", self.root / "private", self.lots.key)                  # a restart keeps both
        self.assertEqual((again.reserves[lot], again.lots[lot]["bids"][0]["price"]), (1234, 45))

    def test_closing_awards_what_the_seller_named_and_waits_for_the_rest(self):
        a = self.lot(start=40, reserve=60)["id"]
        b = self.lots.create("t04", {"card": "SAL-09"}, CARD, {"SAL-09"}, 100)["id"]                         # no reserve
        c = self.lots.create("t04", {"card": "SAL-08", "reserve": 90}, CARD, {"SAL-08"}, 100)["id"]
        d = self.lots.create("t04", {"card": "SAL-07"}, CARD, {"SAL-07"}, 100)["id"]                         # nobody bids
        for lot, price in ((a, 60), (b, 50), (c, 70)):
            self.lots.bid("t05", lot, {"price": price}, 110)
        self.sync(139)
        self.assertEqual({x["state"] for x in self.lots.lots.values()}, {"open"})
        self.sync(140)
        state = lambda k: self.lots.lots[k]["state"]          # noqa: E731
        self.assertEqual((state(a), state(b), state(c), state(d)), ("awarded", "ended", "ended", "unsold"))
        self.assertEqual(self.awards, [(a, "t05", 60)])
        self.assertRaises(PlazaError, self.lots.accept, "t05", b, 141, self.award)                             # only its seller
        self.assertEqual(self.lots.accept("t04", b, 141, self.award)["state"], "awarded")                     # no reserve: its call
        self.assertTrue(self.lots.accept("t04", b, 142, self.award)["repeated"])
        self.assertEqual(self.lots.cancel("t04", c, 141)["state"], "cancelled")                               # no bid reached its reserve
        self.assertRaises(PlazaError, self.lots.cancel, "t04", a, 141)
        self.assertRaises(PlazaError, self.lots.accept, "t04", d, 141, self.award)

    def test_an_ended_lot_nobody_takes_goes_unsold_and_ask_me_is_not_awarded_alone(self):
        a = self.lot(reserve=50)["id"]
        self.lots.bid("t05", a, {"price": 55}, 110)
        self.sync(140, auto=False)
        self.assertEqual((self.lots.lots[a]["state"], self.awards), ("ended", []))
        self.sync(140 + L.ACCEPT_TICKS + 1, auto=False)
        self.assertEqual(self.lots.lots[a]["state"], "unsold")

    def test_a_winner_that_does_not_post_loses_the_lot_to_the_next_bid_and_is_struck(self):
        a = self.lot(reserve=40)["id"]
        self.lots.bid("t05", a, {"price": 40}, 110)
        self.lots.bid("t06", a, {"price": 45}, 111)
        self.sync(140)
        mid = self.lots.lots[a]["match"]
        self.assertEqual(self.awards, [(a, "t06", 45)])
        self.sync(140 + L.POST_TICKS)                          # still in time
        self.assertEqual((self.lots.lots[a]["state"], self.defaults), ("awarded", []))
        self.sync(141 + L.POST_TICKS)
        self.assertEqual((self.defaults, self.expired), ([(a, "t06")], [mid]))
        self.assertEqual(self.lots.lots[a]["state"], "ended")
        self.sync(142 + L.POST_TICKS)
        self.assertEqual(self.awards[-1], (a, "t05", 40))      # the next best bid met the reserve: awarded at once
        self.assertEqual([(b["team"], b["state"]) for b in self.lots.lots[a]["bids"]], [("t05", "live"), ("t06", "defaulted")])
        self.matches[self.lots.lots[a]["match"]]["state"] = "settled"
        self.sync(160)
        self.assertEqual((self.lots.lots[a]["state"], self.lots.lots[a]["winner"], self.lots.lots[a]["price"]), ("settled", "t05", 40))
        self.assertEqual(self.sync(161), [])                   # and nothing moves a settled lot
        self.assertEqual(self.lots.cancel(None, self.lot(tick=200)["id"], 201)["state"], "cancelled")         # our panel: any live lot
        self.assertRaises(PlazaError, self.lots.cancel, None, a, 201)

    def test_an_offer_reported_in_time_is_not_a_default(self):
        a = self.lot(reserve=40)["id"]
        self.lots.bid("t05", a, {"price": 40}, 110)
        self.sync(140)
        self.matches[self.lots.lots[a]["match"]]["state"] = "offer_on_v07"
        self.sync(200)
        self.assertEqual((self.lots.lots[a]["state"], self.defaults), ("awarded", []))

    def test_teams_that_want_the_card_are_told_once(self):
        a = self.lot()["id"]
        (act,) = self.lots.actions("t05", {"SAL-10"})
        self.assertEqual((act["type"], act["lot"], act["next_bid"], act["request"]["method"], act["bid"]["body"], len(act["id"])),
                         ("auction", a, 40, "GET", {"price": 40}, 14))
        self.assertEqual((self.lots.actions("t04", {"SAL-10"}), self.lots.actions("t06", {"LAV-11"})), ([], []))
        self.assertFalse(self.lots.ack("t06", act["id"]))
        self.assertTrue(self.lots.ack("t05", act["id"]))
        self.assertEqual(self.lots.actions("t05", {"SAL-10"}), [])

    def test_the_table_of_states(self):
        for state in L.DONE:
            self.assertEqual(L.MOVES[state], set())
        lot = self.lots.lots[self.lot()["id"]]
        self.assertFalse(self.lots._move(lot, "settled", 1))
        self.assertTrue(self.lots._move(lot, "cancelled", 1))
        self.assertFalse(self.lots._move(lot, "open", 2))


class HttpTest(unittest.TestCase):
    """Through HTTP, with test_server's public sheet: t09 lists LAT-06 for sale; t07 and t05 bid for it."""
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call
    connect, event = DA.RoutesTest.connect, DA.RoutesTest.event

    def test_from_a_lot_to_a_sale_settled_on_our_venue(self):
        seller, a, b = self.connect("t09"), self.connect("t07"), self.connect("t05")
        st, lot, _ = self.call("POST", "/plaza/api/lots", {"card": "LAT-06", "start": 20, "reserve": 1777}, seller)
        self.assertEqual((st, lot["state"], lot["you"]["reserve_set"]), (201, "open", True))
        lid = lot["id"]
        self.assertEqual(self.call("POST", "/plaza/api/lots", {"card": "LAT-06"}, seller)[0], 200)            # repeated
        for headers, path, body, want in ((None, f"/plaza/api/lot/{lid}/bid", {"price": 25}, 401),
                                          (seller, f"/plaza/api/lot/{lid}/bid", {"price": 25}, 403),
                                          (a, f"/plaza/api/lot/{lid}/bid", {"price": 5}, 409),
                                          (a, f"/plaza/api/lot/{lid}/bid", {"price": "25"}, 400),
                                          (a, f"/plaza/api/lot/{lid}/accept", {}, 403),
                                          (a, f"/plaza/api/lot/{lid}/cancel", {}, 403),
                                          (a, "/plaza/api/lot/l-ffffffff/bid", {"price": 25}, 404),
                                          (a, "/plaza/api/lots", {"card": "LAV-12"}, 400)):
            self.assertEqual(self.call("POST", path, body, headers)[0], want, (path, body))
        self.assertEqual(self.call("POST", f"/plaza/api/lot/{lid}/bid", {"price": 20}, a)[0], 200)
        st, out, _ = self.call("POST", f"/plaza/api/lot/{lid}/bid", {"price": 25}, b)
        self.assertEqual((st, out["best_bidder"], out["you"]["winning"]), (200, "t05", True))
        st, pub, head = self.call("GET", "/plaza/lots.json")
        self.assertEqual((st, head.get("Access-Control-Allow-Origin"), pub["lots"][0]["best_bid"], pub["lots"][0]["bid_count"]), (200, "*", 25, 2))
        self.assertNotIn("you", pub["lots"][0])
        for text in (json.dumps(pub), json.dumps(self.call("GET", f"/plaza/api/lot/{lid}", headers=b)[1]),
                     json.dumps(self.call("GET", "/plaza/admin/api/trades", headers=ADMIN)[1]),
                     "".join(p.read_text(errors="replace") for p in self.live.glob("*") if p.is_file())):
            self.assertIsNone(re.search(r'[:\s]1777[,}\s]|"reserve"', text))    # the reserve: nowhere but with its seller
        st, out, _ = self.call("POST", f"/plaza/api/lot/{lid}/accept", {}, seller)                            # under its reserve, its call
        self.assertEqual((st, out["state"], out["winner"], out["price"]), (200, "awarded", "t05", 25))
        mid = out["match"]
        acts = self.call("GET", "/plaza/api/agent/next", headers=b)[1]["actions"]
        post = next(x for x in acts if x["type"] == "post_offer")
        self.assertEqual((post["match"], post["request"]["body"]["venue"], post["request"]["body"]["to"],
                          post["request"]["body"]["give"]), (mid, "v07", "t09", {"cash": 25}))
        self.assertFalse([x for x in self.call("GET", "/plaza/api/agent/next", headers=seller)[1]["actions"] if x["type"] == "decide"])
        self.event(id=3, tick=81, type="offer.listed", payload={"offer": {
            "id": 77, "maker": "t05", "to": "t09", "venue": "v07", "give": {"cash": 25}, "want": {"cards": ["LAT-06"]}, "created_tick": 81}})
        self.board.rebuild()
        acts = self.call("GET", "/plaza/api/agent/next", headers=seller)[1]["actions"]
        self.assertIn("accept_offer", [x["type"] for x in acts])
        self.event(id=4, tick=82, type="settlement", payload={"settlement": 9, "venue": "v07", "price": 25, "parties": ["t05", "t09"],
                                                               "items": [{"ref": "LAT-06", "frm": "t09", "to": "t05"}]})
        self.board.rebuild()
        st, out, _ = self.call("GET", f"/plaza/api/lot/{lid}")
        self.assertEqual((out["state"], out["winner"], out["price"]), ("settled", "t05", 25))
        self.assertEqual(self.board.deals.get(mid)["state"], "settled")
        self.assertEqual(self.call("POST", f"/plaza/api/lot/{lid}/bid", {"price": 90}, a)[0], 409)

    def test_a_winner_that_never_posts_takes_a_strike(self):
        seller, a = self.connect("t09"), self.connect("t07")
        lid = self.call("POST", "/plaza/api/lots", {"card": "LAT-06", "start": 20}, seller)[1]["id"]
        self.call("POST", f"/plaza/api/lot/{lid}/bid", {"price": 20}, a)
        self.assertEqual(self.call("POST", f"/plaza/api/lot/{lid}/accept", {}, seller)[1]["state"], "awarded")
        now = self.board.lots.tick
        self.event(id=3, tick=now + L.POST_TICKS + 2, type="pack.opened", payload={"team": "t01", "pack": "x"})
        self.board.rebuild()
        self.assertEqual(self.board.lots.lots[lid]["state"], "ended")
        self.assertEqual(self.board.strikes.standing("t07")["strikes"], 1)
        self.assertEqual(self.board.strikes.standing("t09")["strikes"], 0)

    def test_a_banned_team_the_host_and_garbage(self):
        seller, a = self.connect("t09"), self.connect("t07")
        lid = self.call("POST", "/plaza/api/lots", {"card": "LAT-06", "start": 20}, seller)[1]["id"]
        self.board.strikes.ban("t07", "abuse")
        self.assertEqual(self.call("POST", f"/plaza/api/lot/{lid}/bid", {"price": 20}, a)[0], 403)
        for body in (None, [], "x", {"price": None}, {"price": -1}, {"price": 1e99}, {"price": [1]}, {"card": {"a": 1}}, {"x": "y" * 9000}):
            for path in ("/plaza/api/lots", f"/plaza/api/lot/{lid}/bid", f"/plaza/api/lot/{lid}/accept", f"/plaza/api/lot/{lid}/cancel"):
                st = self.call("POST", path, body, seller)[0]
                self.assertTrue(400 <= st < 500 or (st == 200 and path.endswith(("lots", "cancel"))), (path, body, st))
        self.assertEqual(self.call("GET", "/plaza/api/health")[0], 200)
        st, out, _ = self.call("POST", "/plaza/admin/api/action", {"action": "lot_cancel", "lot": lid}, ADMIN)
        self.assertIn(st, (200, 409))                          # ours to cancel, unless its seller already did
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "lot_cancel", "lot": lid, "price": 1}, ADMIN)[0], 400)


if __name__ == "__main__":
    unittest.main()
