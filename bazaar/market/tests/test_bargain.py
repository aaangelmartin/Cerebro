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

    def test_bargain_we_cannot_fund_is_a_watch_note_not_an_alarm(self):
        """Outbox request code-3fd35e4c: no spares to sell, so the alert must not wake a plan."""
        self.run_tick(cash=104, control={"cash_reserve": 5})
        row = bargain.recent(since=0)[-1]
        self.assertIs(row["feasible"], False)
        self.assertEqual(row["liquid"], 0)
        text = bargain.event_text(row)
        self.assertIn("Watch only", text)
        self.assertNotIn("FUND IT NOW", text)

    def test_feasible_needs_spares_and_time(self):
        self.assertTrue(bargain.feasible(40, 60, None))
        self.assertTrue(bargain.feasible(40, 60, 5))
        self.assertFalse(bargain.feasible(40, 60, 3))              # expires before we can sell anything
        self.assertFalse(bargain.feasible(112, 60, 30))            # the spares do not cover the shortfall

    def test_gain_does_not_add_the_page_bonus_to_an_exact_value(self):
        """MAL-09 on Saturday: exact value 177.1 (91 + 86.1 of page bonus) at 148 all-in is +29.1, not +115.2."""
        from bazaar.dealers.values import Values
        d = dom()
        o = lav11(price=80)

        def gain(exact):
            v = Values(sit().me, d.catalog(None), {})
            if exact:
                v.remember_exact("LAV-11", {"your_value": 200.0})
            with mock.patch("bazaar.market.domain.page_delta", return_value=50.0):
                c = d._evaluate(o, RASTRO, v, {}, lambda a, left: True)
            return c.gain, c.value_in, c.fee

        g, value, fee = gain(exact=True)
        self.assertEqual((value, g), (200.0, round(200.0 - 80 - fee, 2)))
        g, value, fee = gain(exact=False)                              # an estimate has no bonus inside: add it
        self.assertEqual(g, round(value - 80 - fee + 50.0, 2))

    def test_exact_value_that_holds_the_page_bonus_is_not_counted_twice(self):
        row = {"refs": ["MAL-09"], "seller": "t13", "venue": "rastro", "offer": 13680, "price": 140, "cost": 148,
               "value": 177.1, "gain": 29.1, "page_bonus": 86.1, "status": "accepting"}
        self.assertIn("page bonus of 86.1 P included", bargain.event_text(row))

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
