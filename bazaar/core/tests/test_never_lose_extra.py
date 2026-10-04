"""Extra cases for the never-lose rails: duels against our limit, addressed offers on allied/own venues,
unknown values. Every case here passes against the current rails."""
import unittest

from bazaar.core import rails
from bazaar.core.types import Action


def sit(**kw):
    base = {"me": {"id": "t10", "cash": 200, "assets": [
        {"id": 1, "kind": "card", "ref": "SAL-07", "your_value": 22.5},
        {"id": 2, "kind": "card", "ref": "LAV-04", "your_value": 16.0},
        {"id": 3, "kind": "card", "ref": "SAL-01", "your_value": None}]},
        "values": {"card:MAL-09": 91.0, "MAL-09": 91.0, "card:RET-03": 11.0, "RET-03": 11.0},
        "venues": [{"venue": "rastro", "fee_bps": 500, "fee_per_card": 1}, {"venue": "v07", "fee_bps": 0},
                   {"venue": "v10", "fee_bps": 0, "fee_per_card": 0}],
        "duels": [{"duel": 5, "status": "live", "role": "buyer", "your_limit": 73, "issues": ["price"]},
                  {"duel": 6, "status": "live", "role": "seller", "your_limit": 40, "issues": ["price", "days"]}],
        "threads": [], "my_offers": []}
    base.update(kw)
    return base


def act(kind, params, expected=None):
    return Action(kind=kind, params=params, domain="market", expected=expected or {})


class DuelLimitTest(unittest.TestCase):
    def test_buyer_never_pays_above_limit(self):
        self.assertFalse(rails.rail_duel(act("duel_accept", {"duel": 5, "expect": {"price": 73}}), sit(), None).ok)
        self.assertFalse(rails.rail_duel(act("duel_message", {"duel": 5, "price": 80}), sit(), None).ok)
        self.assertTrue(rails.rail_duel(act("duel_accept", {"duel": 5, "expect": {"price": 60}}), sit(), None).ok)

    def test_seller_never_sells_below_limit(self):
        self.assertFalse(rails.rail_duel(act("duel_accept", {"duel": 6, "expect": {"price": 40, "days": 3}}), sit(), None).ok)
        self.assertTrue(rails.rail_duel(act("duel_message", {"duel": 6, "price": 55, "days": 3}), sit(), None).ok)

    def test_accept_without_price_or_unknown_duel_is_vetoed(self):
        self.assertFalse(rails.rail_duel(act("duel_accept", {"duel": 5, "expect": {}}), sit(), None).ok)
        self.assertFalse(rails.rail_duel(act("duel_accept", {"duel": 99, "expect": {"price": 1}}), sit(), None).ok)


class AddressedOffersTest(unittest.TestCase):
    def test_addressed_ask_on_allied_or_own_venue_still_needs_value(self):
        for venue in ("v07", "v10"):
            low = act("post_offer", {"venue": venue, "to": "t05", "give": {"assets": [1]}, "want": {"cash": 20}})
            ok = act("post_offer", {"venue": venue, "to": "t05", "give": {"assets": [1]}, "want": {"cash": 24}})
            self.assertFalse(rails.rail_value(low, sit(), None).ok, venue)
            self.assertTrue(rails.rail_value(ok, sit(), None).ok, venue)


class UnknownValueTest(unittest.TestCase):
    def test_buy_of_unknown_card_is_vetoed(self):
        a = act("post_offer", {"venue": "v07", "give": {"cash": 5}, "want": {"cards": ["CHA-01"]}})
        self.assertFalse(rails.rail_value(a, sit(), None).ok)

    def test_sell_of_card_without_value_is_vetoed(self):
        a = act("post_offer", {"venue": "v07", "give": {"assets": [3]}, "want": {"cash": 50}})
        self.assertFalse(rails.rail_value(a, sit(), None).ok)

    def test_proposer_value_gain_is_not_trusted_for_cards(self):
        a = act("post_offer", {"venue": "v07", "give": {"assets": [2]}, "want": {"cash": 9}},
                expected={"value_gain": 50, "value_get": 99})
        self.assertFalse(rails.rail_value(a, sit(), None).ok)


if __name__ == "__main__":
    unittest.main()
