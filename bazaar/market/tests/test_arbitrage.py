"""Dealer -> team arbitrage planner: start only with a secured buyer, sell on arrival, one job at a time."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.market import arbitrage as A

PICAROS = {"id": "picaros", "status": "active", "open_to_all": False,
           "menu": {"sells": [{"rarity": "rare", "sets": "released", "list_price": 63}], "buys": []}}


def bid(oid=900, ref="MAL-10", cash=90, maker="t17", exp=140, to=None):
    return {"id": oid, "maker": maker, "to": to, "venue": "rastro", "thread": None, "status": "open",
            "give": {"cash": cash, "assets": [], "types": []},
            "want": {"cash": 0, "assets": [], "types": [f"card:{ref}"]}, "expires_tick": exp}


def sit(tick=100, cash=120, assets=None, offers=(), **kw):
    assets = assets if assets is not None else [{"id": 5, "kind": "card", "ref": "MAL-10", "rarity": "rare"}]
    feed = [{"type": "offer.listed", "payload": {"venue": "rastro", "offer": o}} for o in offers]
    return SimpleNamespace(tick=tick, paused=False, doors="open", slow_tick=-1, rastro_book=[], my_offers=[],
                           feed_new=feed, dealers=[PICAROS], threads=[], closed_threads=[],
                           me={"id": "t10", "cash": cash, "unlocked": ["picaros"], "assets": assets}, **kw)


class ArbitrageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        self.arb = A.Arbitrage()

    def tearDown(self):
        self.tmp.cleanup()

    def test_starts_only_with_an_open_bid_and_margin(self):
        self.assertEqual(self.arb.step(sit(), {}, self.live), [])
        self.assertIsNone(A.load(self.live))                                 # no bid: nothing starts
        self.arb.step(sit(offers=[bid(cash=70)]), {}, self.live)             # 70 nets 65: 65 - 55 < 15
        self.assertIsNone(A.load(self.live))
        self.arb.step(sit(offers=[bid(cash=90)]), {}, self.live)
        job = A.load(self.live)
        self.assertEqual((job["ref"], job["dealer"], job["stage"]), ("MAL-10", "picaros", "buying"))
        self.assertEqual(job["resale_net"], 90 - 6)                          # 5 % + 1 P taker fee
        self.assertEqual(job["cap"], 84 - A.MIN_MARGIN_P)
        order = A.dealer_order(self.live)
        self.assertEqual((order["action"], order["bound"], order["arbitrage"]), ("buy", 69, True))

    def test_not_for_cards_we_lack_bids_to_others_or_low_cash(self):
        self.arb.step(sit(offers=[bid(ref="MAL-09")]), {}, self.live)        # we lack it: that copy is ours
        self.arb.step(sit(offers=[bid(to="t03")]), {}, self.live)            # addressed to another team
        self.arb.step(sit(offers=[bid(maker="t10")]), {}, self.live)         # our own bid
        self.arb.step(sit(offers=[bid(exp=104)]), {}, self.live)             # dies too soon
        self.arb.step(sit(cash=50, offers=[bid()]), {"cash_reserve": 15}, self.live)   # cannot pay ~55 + reserve
        self.assertIsNone(A.load(self.live))
        self.arb.step(sit(offers=[bid()]), {}, self.live, mode="off")        # the brain switched it off
        self.assertIsNone(A.load(self.live))

    def test_one_job_at_a_time_and_abort_when_the_bid_goes(self):
        self.arb.step(sit(offers=[bid(), bid(oid=901, ref="MAL-10", cash=95)]), {}, self.live)
        first = A.load(self.live)["bid"]["id"]
        self.arb.step(sit(tick=101, offers=[bid(oid=902, cash=99)]), {}, self.live)
        self.assertEqual(A.load(self.live)["bid"]["id"], first)              # still the first job
        gone = sit(tick=102)
        gone.feed_new = [{"type": "offer.cancelled", "payload": {"offer": first}}]
        self.arb.step(gone, {}, self.live)
        self.assertIsNone(A.load(self.live))                                 # nothing bought: job dropped

    def test_sells_into_the_bid_when_the_card_arrives(self):
        self.arb.step(sit(offers=[bid()]), {}, self.live)
        two = [{"id": 5, "kind": "card", "ref": "MAL-10"}, {"id": 77, "kind": "card", "ref": "MAL-10"}]
        acts = self.arb.step(sit(tick=103, cash=66, assets=two), {}, self.live)
        self.assertEqual(len(acts), 1)
        a = acts[0]
        self.assertEqual((a.kind, a.params["offer"], a.params["assets"]), ("accept_offer", 900, [77]))
        self.assertEqual(a.params["give"]["cash"], 6)                        # the fee we pay as the taker
        self.assertEqual(A.load(self.live)["stage"], "selling")
        self.assertIsNone(A.dealer_order(self.live))                         # no more buying
        self.arb.step(sit(tick=104, cash=150), {}, self.live)                # the copy left: sold
        self.assertIsNone(A.load(self.live))
        self.assertEqual([r["step"] for r in A.recent(self.live)], ["start", "bought", "sold"])

    def test_bid_gone_after_buying_becomes_stock(self):
        self.arb.step(sit(offers=[bid()]), {}, self.live)
        two = [{"id": 5, "kind": "card", "ref": "MAL-10"}, {"id": 77, "kind": "card", "ref": "MAL-10"}]
        s = sit(tick=103, assets=two)
        s.feed_new = [{"type": "offer.cancelled", "payload": {"offer": 900}}]
        self.assertEqual(self.arb.step(s, {}, self.live), [])
        self.assertEqual(A.load(self.live)["stage"], "stock")
        # no new job while the card is in stock, and a bid just above cost + 5 is taken (cost = cap 69 here)
        acts = self.arb.step(sit(tick=104, assets=two, offers=[bid(oid=950, cash=70)]), {}, self.live)
        self.assertEqual(acts, [])
        acts = self.arb.step(sit(tick=105, assets=two, offers=[bid(oid=951, cash=82)]), {}, self.live)
        self.assertEqual(acts[0].params["offer"], 951)


if __name__ == "__main__":
    unittest.main()
