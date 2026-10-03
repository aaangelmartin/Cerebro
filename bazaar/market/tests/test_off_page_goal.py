"""A goal outside the page (an epic nº 11, a legendary nº 12) is bought from a TEAM: the market bids for it at
the goal price, below its value to us, and the dealers' code never sees it (code-c55a780a)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bazaar import config
from bazaar.brain import strategy as S
from bazaar.core.goal import goal_sets, off_page, pending, team_only
from bazaar.dealers.values import Values
from bazaar.market.domain import MarketDomain
from bazaar.market.rivals import RivalModel
from bazaar.strategist import brainio

RARITY = ["common"] * 5 + ["uncommon"] * 3 + ["rare"] * 2
BOOK = {"common": 10, "uncommon": 25, "rare": 70}
CARDS = ([{"id": f"LAV-{i:02d}", "rarity": r, "book": BOOK[r], "page": True} for i, r in enumerate(RARITY, 1)]
         + [{"id": "LAV-11", "rarity": "epic", "book": 180, "page": False},
            {"id": "LAV-12", "rarity": "legendary", "book": 450, "page": False}])
CATALOG = {"values": {"page_bonus": 0.25, "copy_marginals": [1.0, 0.25, 0.1]},
           "sets": [{"id": "LAV", "released": True, "cards": CARDS}]}


def me(extra=(), cash=600):
    assets = [{"id": i, "kind": "card", "ref": f"LAV-{i:02d}", "rarity": r, "set": "LAV", "your_value": 16}
              for i, r in enumerate(RARITY, 1)]
    assets += [{"id": 90 + n, "kind": "card", "ref": ref, "rarity": "epic", "set": "LAV", "your_value": 288}
               for n, ref in enumerate(extra)]
    return {"id": "t10", "cash": cash, "affinity": {"LAV": 1.6}, "assets": assets}


def prepare(goals, extra=(), cash=600, my_offers=(), per_deal=240):
    sit = SimpleNamespace(tick=10, me=me(extra, cash), my_offers=list(my_offers), threads=[], venues=[],
                          feed_new=[], limits={}, books={})
    ctx = SimpleNamespace(control={"venue_reserve": False, "max_spend_per_deal": per_deal}, budget={},
                          cautious=False, llm_ok=False)
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


class OffPageGoal(unittest.TestCase):
    def test_an_epic_is_off_the_page_and_kept_for_a_team_seller(self):
        v = Values(me(), CATALOG)
        self.assertTrue(off_page(v, "LAV-11"))
        self.assertFalse(off_page(v, "LAV-05"))
        self.assertTrue(team_only(v, {}, "LAV-11"))
        self.assertFalse(team_only(v, {"goal_buys": {"LAV-11": 230}}, "LAV-11"))   # an operator goal: any seller
        with mock.patch.object(S, "goal_buys", return_value={"LAV-11": 230}):
            self.assertEqual(pending({"me": me()}, {}, v), {})                     # the dealers never see it
            self.assertEqual(pending({"me": me()}, {}, v, team=True), {"LAV-11": 230})
            self.assertEqual(goal_sets({}, v), set())                              # and it builds no page

    def test_public_bid_at_the_goal_price(self):
        bids = prepare({"LAV-11": 230})["_bids"]
        self.assertEqual([(b.ref, b.price) for b in bids], [("LAV-11", 230)])
        self.assertAlmostEqual(bids[0].value, 288.0)

    def test_the_bid_stays_below_value_and_inside_the_deal_cap(self):
        self.assertEqual(prepare({"LAV-11": 400})["_bids"][0].price, 240)              # the operator's per-deal cap
        self.assertEqual(prepare({"LAV-11": 400}, per_deal=500)["_bids"][0].price, 287)  # one below its value

    def test_no_bid_for_a_card_we_hold(self):
        self.assertEqual(prepare({"LAV-11": 230}, extra=("LAV-11",))["_bids"], [])

    def test_open_bid_is_kept_and_posted_again_once_it_expired(self):
        mine = {"id": 7, "maker": "t10", "status": "open", "venue": "rastro", "give": {"cash": 230},
                "want": {"types": ["card:LAV-11"]}}
        state = prepare({"LAV-11": 230}, my_offers=[mine])
        self.assertEqual(state["_bids"], [])
        self.assertNotIn(7, [o.get("id") for o, _ in state["_stale"]])
        self.assertEqual([b.ref for b in prepare({"LAV-11": 230})["_bids"]], ["LAV-11"])   # gone from the book


class PlanCheck(unittest.TestCase):
    PIC = {"held_refs": ["LAV-01", "MAL-11"],
           "sets": {"LAV": {"missing": [], "off_page": [{"ref": "LAV-11", "value_to_us": 288.0},
                                                         {"ref": "LAV-12", "value_to_us": 720.0}]},
                    "SAL": {"missing": [{"ref": "SAL-06", "value_to_us": 22.5}], "off_page": []}}}

    def errs(self, goals):
        return [e for e in brainio.validate({"goal_buys": goals}, self.PIC) if e.startswith("goal")]

    def test_an_epic_goal_below_its_value_is_accepted(self):
        self.assertEqual(self.errs({"LAV-11": 230}), [])

    def test_an_epic_goal_at_or_above_its_value_is_rejected(self):
        self.assertTrue(any("not below its value" in e for e in self.errs({"LAV-11": 288})))

    def test_held_and_unknown_cards_are_still_rejected(self):
        self.assertTrue(any("already hold" in e for e in self.errs({"MAL-11": 100})))
        self.assertTrue(any("not a missing page card" in e for e in self.errs({"RET-11": 100})))

    def test_page_goals_are_unchanged(self):
        self.assertEqual(self.errs({"SAL-06": 20}), [])
        self.assertTrue(any("not below its value" in e for e in self.errs({"SAL-06": 23})))


if __name__ == "__main__":
    unittest.main()
