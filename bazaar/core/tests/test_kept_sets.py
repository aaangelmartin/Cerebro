"""Keep-the-last-copy applies to the sets we collect; an avoided set's last copy may be sold above value."""
import unittest

from bazaar.core import rails
from bazaar.core.types import Action

AVOID_RET = {"control": {"avoid_buy_sets": ["RET"]}}


def sit():
    return {"me": {"id": "t10", "cash": 50, "assets": [
        {"id": 1, "kind": "card", "ref": "RET-06", "your_value": 27.5},
        {"id": 2, "kind": "card", "ref": "MAL-07", "your_value": 40.0}]},
        "venues": [{"venue": "rastro", "fee_bps": 500, "fee_per_card": 1}],
        "threads": [{"id": 5, "with": "pilar", "topic": {"sell": {"assets": [1]}}, "messages": []}]}


def ask(asset, cash):
    return Action(kind="post_offer", params={"venue": "rastro", "give": {"assets": [asset]}, "want": {"cash": cash}},
                  domain="market")


class KeptSetsTest(unittest.TestCase):
    def test_kept_sets_drops_avoided(self):
        self.assertEqual(rails.kept_sets({}), {"LAV", "MAL", "RET"})
        self.assertEqual(rails.kept_sets({"avoid_buy_sets": ["ret", "SAL"]}), {"LAV", "MAL"})

    def test_avoided_set_last_copy_can_be_sold_above_value(self):
        a = ask(1, 31)
        self.assertTrue(rails.rail_cards(a, sit(), AVOID_RET).ok)
        self.assertTrue(rails.rail_value(a, sit(), AVOID_RET).ok)

    def test_avoided_set_last_copy_below_value_is_vetoed(self):
        a = ask(1, 25)
        self.assertTrue(rails.rail_cards(a, sit(), AVOID_RET).ok)
        self.assertFalse(rails.rail_value(a, sit(), AVOID_RET).ok)

    def test_collected_set_last_copy_is_vetoed(self):
        self.assertFalse(rails.rail_cards(ask(2, 60), sit(), AVOID_RET).ok)
        self.assertFalse(rails.rail_cards(ask(1, 31), sit(), {"control": {}}).ok)   # RET not avoided: rule is back

    def test_dealer_sell_of_avoided_last_copy(self):
        a = Action(kind="thread_message", params={"thread": 5, "price": 32}, domain="dealers")
        self.assertTrue(rails.rail_cards(a, sit(), AVOID_RET).ok)
        self.assertFalse(rails.rail_cards(a, sit(), {"control": {}}).ok)


if __name__ == "__main__":
    unittest.main()
