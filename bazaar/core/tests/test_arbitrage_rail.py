"""The arbitrage exception of the value rail: a dealer buy above the spare's value passes only with a secured
resale (an open team bid) and inside every bound the team approved."""
import unittest

from bazaar.core import rails
from bazaar.core.types import Action


def job(**kw):
    j = {"ref": "MAL-10", "dealer": "picaros", "stage": "buying", "cap": 70, "seen_tick": 100, "held_before": [5],
         "resale_net": 85, "bid": {"id": 900, "cash": 90, "maker": "t17", "venue": "rastro", "expires_tick": 120}}
    j.update(kw)
    return j


def sit(**kw):
    s = {"tick": 100, "me": {"id": "t10", "cash": 100, "assets": [
        {"id": 5, "kind": "card", "ref": "MAL-10", "your_value": 91.0}]},
        "values": {"card:MAL-10": 9.0, "MAL-10": 9.0},        # a second copy is worth little to us
        "my_offers": [], "rastro_book": [],
        "threads": [{"id": 7, "with": "picaros", "topic": {"buy": {"card": "MAL-10"}}, "messages": []},
                    {"id": 8, "with": "chato", "topic": {"buy": {"card": "MAL-10"}}, "messages": []}]}
    s.update(kw)
    return s


def buy(price, thread=7):
    return Action(kind="thread_message", params={"thread": thread, "price": price}, domain="dealers")


def value(action, s=None, **ctx):
    return rails.rail_value(action, s or sit(), {"arbitrage": job(), "control": {"cash_reserve": 15}, **ctx})


class ArbitrageRailTest(unittest.TestCase):
    def test_without_a_job_the_buy_is_vetoed(self):
        self.assertFalse(rails.rail_value(buy(54), sit(), {"arbitrage": {}}).ok)

    def test_secured_buy_passes(self):
        self.assertTrue(value(buy(54)).ok)
        self.assertTrue(value(Action(kind="open_thread", domain="dealers",
                                     params={"with": "picaros", "topic": {"buy": {"card": "MAL-10"}}, "price": 45})).ok)

    def test_price_above_the_cap_is_vetoed(self):
        # bid 90 nets 90 - (5 % + 1) = 84; the margin of 15 allows 69 at most, and the job's cap 70 cannot lift it
        self.assertTrue(value(buy(69)).ok)
        r = value(buy(70))
        self.assertFalse(r.ok)
        self.assertIn("cap", r.detail)

    def test_another_dealer_or_card_is_not_covered(self):
        self.assertFalse(value(buy(54, thread=8)).ok)                        # chato is not the job's dealer
        other = sit(threads=[{"id": 7, "with": "picaros", "topic": {"buy": {"card": "SAL-09"}}, "messages": []}],
                    values={"card:SAL-09": 9.0})
        self.assertFalse(value(buy(54), other).ok)

    def test_bid_must_be_seen_open_now(self):
        self.assertFalse(value(buy(54), arbitrage=job(seen_tick=97)).ok)
        book = sit(rastro_book=[{"id": 900, "maker": "m12", "give": {"cash": 90}}])
        self.assertTrue(value(buy(54), book, arbitrage=job(seen_tick=97)).ok)

    def test_bid_must_not_be_ours(self):
        self.assertFalse(value(buy(54), arbitrage=job(bid={"id": 900, "cash": 90, "maker": "t10",
                                                           "expires_tick": 120})).ok)
        self.assertFalse(value(buy(54), sit(my_offers=[{"id": 900}])).ok)

    def test_bid_must_live_three_more_ticks(self):
        short = job(bid={"id": 900, "cash": 90, "maker": "t17", "expires_tick": 102})
        self.assertFalse(value(buy(54), arbitrage=short).ok)
        self.assertTrue(value(buy(54), arbitrage=job(bid={"id": 900, "cash": 90, "maker": "t17",
                                                          "expires_tick": 103})).ok)

    def test_only_while_buying_and_one_card_in_transit(self):
        self.assertFalse(value(buy(54), arbitrage=job(stage="selling")).ok)
        two = sit()
        two["me"]["assets"].append({"id": 6, "kind": "card", "ref": "MAL-10", "your_value": 9.0})
        self.assertFalse(value(buy(54), two).ok)

    def test_cash_must_stay_above_the_reserve(self):
        poor = sit()
        poor["me"]["cash"] = 60
        self.assertFalse(value(buy(54), poor).ok)
        self.assertTrue(value(buy(45), poor).ok)

    def test_selling_the_extra_copy_into_the_bid_passes_the_normal_rail(self):
        s = sit()
        s["me"]["assets"].append({"id": 6, "kind": "card", "ref": "MAL-10", "your_value": 9.0})
        a = Action(kind="accept_offer", domain="market",
                   params={"offer": 900, "assets": [6], "give": {"cash": 6, "assets": [6]}, "want": {"cash": 90},
                           "expect": {"venue": "rastro", "maker": "t17", "give": {"cash": 90},
                                      "want": {"types": ["card:MAL-10"]}}})
        self.assertTrue(rails.rail_value(a, s, None).ok)


if __name__ == "__main__":
    unittest.main()
