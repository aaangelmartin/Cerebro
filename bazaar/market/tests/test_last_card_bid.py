"""The market bids for the common/uncommon that completes a page: only a team sale of it scores (code-2051e7c2)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bazaar import config
from bazaar.brain import strategy as S
from bazaar.market.domain import MarketDomain
from bazaar.market.rivals import RivalModel

RARITY = ["common"] * 5 + ["uncommon"] * 3 + ["rare"] * 2
BOOK = {"common": 10, "uncommon": 25, "rare": 70}
CATALOG = {"values": {"page_bonus": 0.25, "copy_marginals": [1.0, 0.25, 0.1]},
           "sets": [{"id": "SAL", "released": True,
                     "cards": [{"id": f"SAL-{i:02d}", "rarity": r, "book": BOOK[r], "page": True}
                               for i, r in enumerate(RARITY, 1)]}]}


def prepare(missing, goals, cash=100, my_offers=()):
    assets = [{"id": i, "kind": "card", "ref": f"SAL-{i:02d}", "rarity": r, "set": "SAL", "your_value": 9}
              for i, r in enumerate(RARITY, 1) if f"SAL-{i:02d}" not in missing]
    me = {"id": "t10", "cash": cash, "affinity": {"SAL": 0.9}, "assets": assets}
    sit = SimpleNamespace(tick=10, me=me, my_offers=list(my_offers), threads=[], venues=[], feed_new=[], limits={},
                          books={})
    ctx = SimpleNamespace(control={"venue_reserve": False}, budget={}, cautious=False, llm_ok=False)
    d = MarketDomain(rivals=RivalModel(Path(tempfile.mkdtemp()) / "r.json", seed=False), catalog=CATALOG,
                     use_llm=False)
    with mock.patch.object(config, "LIVE", Path(tempfile.mkdtemp())), \
            mock.patch.object(S, "dealer_orders", return_value=[]), \
            mock.patch.object(S, "post_offers", return_value=[]), \
            mock.patch.object(S, "reserved_refs", return_value=set()), \
            mock.patch.object(S, "workshop_orders", return_value="auto"), \
            mock.patch.object(S, "goal_buys", return_value=goals):
        _, _, state = d._prepare(sit, ctx)
    return state


class LastCardBid(unittest.TestCase):
    def test_bid_for_the_last_common_at_the_goal_price(self):
        bids = prepare({"SAL-05"}, {"SAL-05": 30})["_bids"]
        self.assertEqual([(b.ref, b.price) for b in bids], [("SAL-05", 30)])
        self.assertGreater(bids[0].value, 60)                               # 9 + the 59.6 page bonus

    def test_the_bid_never_passes_three_times_book_or_the_goal(self):
        self.assertEqual(prepare({"SAL-05"}, {"SAL-05": 55})["_bids"][0].price, 30)
        self.assertEqual(prepare({"SAL-05"}, {"SAL-05": 14})["_bids"][0].price, 14)

    def test_no_bid_while_other_cards_are_missing_or_for_a_rare(self):
        self.assertEqual(prepare({"SAL-05", "SAL-09"}, {"SAL-05": 8, "SAL-09": 60})["_bids"], [])
        self.assertEqual(prepare({"SAL-10"}, {"SAL-10": 60})["_bids"], [])   # a rare comes from the dealers

    def test_our_open_bid_for_it_is_kept_and_not_doubled(self):
        mine = {"id": 7, "maker": "t10", "status": "open", "venue": "rastro", "give": {"cash": 30},
                "want": {"types": ["card:SAL-05"]}}
        state = prepare({"SAL-05"}, {"SAL-05": 30}, my_offers=[mine])
        self.assertEqual(state["_bids"], [])
        self.assertNotIn(7, [o.get("id") for o, _ in state["_stale"]])


if __name__ == "__main__":
    unittest.main()
