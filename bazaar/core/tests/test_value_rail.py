"""The universal value rail: every trade must leave us at least +1 P at our private values."""
import unittest

from bazaar.core import rails
from bazaar.core.types import Action


def sit(**kw):
    return {"me": {"id": "t10", "cash": 100, "assets": [
        {"id": 1, "kind": "card", "ref": "SAL-07", "your_value": 22.5},
        {"id": 2, "kind": "card", "ref": "LAV-04", "your_value": 16.0}]},
        "values": {"card:MAL-09": 91.0, "card:RET-03": 11.0, "MAL-09": 91.0, "RET-03": 11.0},
        "venues": [{"venue": "rastro", "fee_bps": 500, "fee_per_card": 1}, {"venue": "v07", "fee_bps": 0}],
        "threads": [{"id": 9, "with": "abuela", "topic": {"buy": {"card": "RET-03"}}, "messages": []},
                    {"id": 8, "with": "abuela", "topic": {"sell": {"assets": [1]}}, "messages": []}], **kw}


def check(kind, params, expected=None):
    return rails.rail_value(Action(kind=kind, params=params, domain="market", expected=expected or {}), sit(), None)


class ValueRailTest(unittest.TestCase):
    def test_ask_must_clear_value_plus_fee(self):
        self.assertFalse(check("post_offer", {"venue": "v07", "give": {"assets": [1]}, "want": {"cash": 23}}).ok)
        self.assertTrue(check("post_offer", {"venue": "v07", "give": {"assets": [1]}, "want": {"cash": 24}}).ok)
        # the taker pays the venue fee: 24 on El Rastro is still +1.5 P for us
        self.assertTrue(check("post_offer", {"venue": "rastro", "give": {"assets": [1]}, "want": {"cash": 24}}).ok)
        # a LAV common worth 16 to us is never dumped at 9
        self.assertFalse(check("post_offer", {"venue": "v07", "give": {"assets": [2]}, "want": {"cash": 9}}).ok)

    def test_bid_must_stay_below_value(self):
        self.assertTrue(check("post_offer", {"venue": "v07", "give": {"cash": 85}, "want": {"cards": ["MAL-09"]}}).ok)
        self.assertFalse(check("post_offer", {"venue": "v07", "give": {"cash": 91}, "want": {"cards": ["MAL-09"]}}).ok)

    def test_swap_must_gain(self):
        self.assertFalse(check("post_offer", {"venue": "v07", "give": {"assets": [1]}, "want": {"cards": ["RET-03"]}}).ok)
        self.assertTrue(check("post_offer", {"venue": "v07", "give": {"assets": [1]}, "want": {"cards": ["MAL-09"]}}).ok)

    def test_accept_offer(self):
        self.assertFalse(check("accept_offer", {"offer": 1, "give": {"cash": 92}, "want": {"types": ["card:MAL-09"]}}).ok)
        self.assertTrue(check("accept_offer", {"offer": 1, "give": {"assets": [1]}, "want": {"cash": 30}}).ok)

    def test_accept_pays_the_taker_fee(self):
        # a Rastro ask for MAL-09 at 89 (value 91): 5 % + 1 P = 5.45 P fee -> a loss
        a = {"offer": 7, "expect": {"venue": "rastro", "give": {"types": ["card:MAL-09"]}, "want": {"cash": 89}}}
        self.assertFalse(check("accept_offer", a).ok)
        a["expect"]["want"]["cash"] = 80
        self.assertTrue(check("accept_offer", a).ok)

    def test_open_thread_buy_price(self):
        self.assertFalse(check("open_thread", {"with": "chato", "topic": {"buy": {"card": "MAL-09"}}, "price": 95}).ok)
        self.assertTrue(check("open_thread", {"with": "chato", "topic": {"buy": {"card": "MAL-09"}}, "price": 80}).ok)

    def test_pack_value_is_not_the_proposers(self):
        r = rails.rail_value(Action(kind="thread_message", params={"thread": 9, "price": 30}, domain="dealers",
                                    expected={"value_get": 100}),
                             {**sit(), "threads": [{"id": 9, "with": "abuela", "topic": {"buy": {"pack": "nope"}},
                                                    "messages": []}]}, None)
        self.assertFalse(r.ok)

    def test_dealer_thread_prices(self):
        self.assertFalse(check("thread_message", {"thread": 9, "price": 11}).ok)     # buy RET-03 at its value
        self.assertTrue(check("thread_message", {"thread": 9, "price": 9}).ok)
        self.assertFalse(check("thread_message", {"thread": 8, "price": 20}).ok)    # sell SAL-07 under value
        self.assertTrue(check("thread_message", {"thread": 8, "price": 25}).ok)

    def test_margin_never_below_one(self):
        class Ctx:
            control = {"caps": {"value_margin": -50}}
        a = Action(kind="post_offer", params={"venue": "v07", "give": {"assets": [1]}, "want": {"cash": 23}}, domain="x")
        self.assertFalse(rails.rail_value(a, sit(), Ctx()).ok)


if __name__ == "__main__":
    unittest.main()
