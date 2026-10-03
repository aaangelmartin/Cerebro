"""The LAV-11 case of Saturday: an epic worth 288 P to us, listed on El Rastro at 125 P for three ticks."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bazaar.market import bargain
from bazaar.market.tests.test_protocol import RASTRO, card, dom, kinds, make_ctx, offer, sit


def lav11(oid=7716, price=125, maker="t08", expires=520):
    o = offer(oid, {"assets": [{"id": 787, "kind": "card", "ref": "LAV-11", "rarity": "epic", "set": "LAV"}]},
              {"cash": price}, maker=maker, venue="rastro")
    o["expires_tick"] = expires
    return o


def listed(o, tick=10):
    return {"type": "offer.listed", "tick": tick, "actor": o.get("maker"), "payload": {"venue": "rastro", "offer": o}}


class BargainCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(bargain.config, "LIVE", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_tick(self, cash, assets=None, control=None):
        d = dom()
        s = sit(assets=assets or [], venues=[RASTRO], cash=cash)
        s.feed_new = [listed(lav11())]                          # only the feed shows it: the book is stale
        ctx = make_ctx(10)
        if control:
            ctx.control = {**(ctx.control or {}), **control}
        return d, d.decide(s, ctx)

    def test_enough_cash_is_accepted_in_the_same_tick_without_council(self):
        d, acts = self.run_tick(cash=200, control={"max_spend_per_deal": 200, "cash_reserve": 5})
        acc = kinds(acts, "accept_offer")
        self.assertEqual(len(acc), 1)
        self.assertEqual(acc[0].params["offer"], 7716)
        self.assertFalse(acc[0].big)                              # no council in the fast path
        self.assertEqual(acc[0].source, "code")
        self.assertGreaterEqual(acc[0].expected["value_gain"], bargain.BIG_BARGAIN_P)
        rows = bargain.recent(since=0)
        self.assertEqual([r["status"] for r in rows], ["accepting"])

    def test_cash_55_counter_offer_and_brain_event(self):
        assets = [card(1, "SAL-10", 63.0), card(2, "RET-06", 27.5), card(3, "LAV-01", 16.0)]
        d, acts = self.run_tick(cash=55, assets=assets, control={"avoid_buy_sets": ["RET", "SAL"], "cash_reserve": 5})
        self.assertFalse(kinds(acts, "accept_offer"))
        posts = [a for a in kinds(acts, "post_offer") if a.params.get("to") == "t08"]
        self.assertEqual(len(posts), 1)
        p = posts[0].params
        self.assertEqual(p["want"], {"cards": ["LAV-11"]})
        self.assertEqual(p["give"]["cash"], 50)
        self.assertNotIn(3, p["give"]["assets"])                  # never a card of a set we collect
        rows = bargain.recent(since=0)
        self.assertEqual(rows[-1]["status"], "short")
        self.assertEqual(rows[-1]["refs"], ["LAV-11"])
        self.assertGreater(rows[-1]["gap"], 0)
        self.assertEqual(bargain.funding()["refs"], ["LAV-11"])
        self.assertIn("FUND IT NOW", bargain.event_text(rows[-1]))

    def test_cash_104_is_still_short_and_tells_the_brain(self):
        d, acts = self.run_tick(cash=104, control={"cash_reserve": 5})
        self.assertFalse(kinds(acts, "accept_offer"))
        row = bargain.recent(since=0)[-1]
        self.assertEqual((row["status"], row["price"]), ("short", 125))
        self.assertEqual(row["gap"], row["cost"] - 99)

    def test_listing_disappears_when_the_card_is_sold(self):
        f = bargain.FeedOffers()
        f.ingest([listed(lav11())], 10)
        self.assertEqual(len(f.open()), 1)
        f.ingest([{"type": "settlement", "payload": {"items": [{"id": 787, "kind": "card", "ref": "LAV-11"}]}}], 11)
        self.assertEqual(f.open(), [])

    def test_counter_never_gives_more_than_60_percent(self):
        pool = [({"id": 1, "ref": "SAL-10"}, 63.0, 70.0)]
        self.assertIsNone(bargain.counter_give(50, 125, 100.0, pool))          # 50 + 63 > 60 % of 100
        g = bargain.counter_give(50, 125, 288.0, pool)
        self.assertEqual((g["cash"], [a["id"] for a in g["assets"]]), (50, [1]))


if __name__ == "__main__":
    unittest.main()
