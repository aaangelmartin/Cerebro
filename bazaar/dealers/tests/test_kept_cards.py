"""Outbox requests code-b294b258 and code-7e4774a6.

Tick 1316: the bot bought SAL-09 from Los Pícaros at 52 for the Salamanca page and, one tick later, its own sell
candidates opened a thread with Doña Pilar and walked the ladder down to a sale at 77. No value was lost, but the
plan kept that card. The code never sells to a dealer, on its own, a card the plan holds back (reserved_refs) or
the only copy of a page we are building (a goal in force); it closes a thread it opened that way. And it never
opens a buy for a second copy of a card we hold: that is the brain's call (a loop, a bridge)."""
from __future__ import annotations

import unittest

import bazaar.brain.strategy as S
import bazaar.core.goal as G
from bazaar.dealers.tests import test_domain as T
from bazaar.dealers.tests import test_steps as ST

SIT, CTX = T.AuditFixes().sit, T.AuditFixes().ctx
# worth 20 to us in this fixture, so that selling it to the fixture's dealer (El Chato pays ~45) is worth opening
SAL09 = {"id": 7, "kind": "card", "ref": "SAL-09", "rarity": "rare", "set": "SAL", "your_value": 20.0}
SAL09_B = {**SAL09, "id": 8}


class Patched(unittest.TestCase):
    """reserved_refs and the page goals of the plan in force, set by hand."""
    reserved: set = set()
    building: set = set()
    orders: list = []

    def setUp(self):
        self._old = (S.reserved_refs, G.goal_sets, S.dealer_orders)
        S.reserved_refs = lambda live=None: set(self.reserved)
        G.goal_sets = lambda control, values=None: set(self.building)
        S.dealer_orders = lambda live=None: list(self.orders)

    def tearDown(self):
        S.reserved_refs, G.goal_sets, S.dealer_orders = self._old

    def sell_opens(self, assets, tick=5):
        dom = T.domain()
        plan = dom._prepare(SIT(tick=tick, assets=[dict(a) for a in assets]), CTX(tick))
        return [c for c in plan.candidates if c.kind.startswith("sell") and c.item == "SAL-09"]

    def sell_thread(self):
        th = ST.raw("chato", "sell")                     # the fixture's dealer that buys rares
        ST.dealer_says(th, 2, 70)
        ST.we_say(th, 3, 92)
        ST.dealer_says(th, 4, 74)
        return th

    def moves(self, assets, tick=5):
        dom = T.domain()
        acts = dom.fallback(SIT(tick=tick, threads=[self.sell_thread()], assets=[dict(a) for a in assets]), CTX(tick))
        return [a for a in acts if a.kind in ("thread_message", "accept_offer", "close_thread")]


class Free(Patched):
    def test_a_free_card_is_still_sold(self):
        self.assertTrue(self.sell_opens([SAL09]))
        self.assertEqual([a.kind for a in self.moves([SAL09])], ["thread_message"])       # the ladder walks on


class Reserved(Patched):
    reserved = {"SAL-09"}

    def test_no_sell_thread_is_opened(self):
        self.assertEqual(self.sell_opens([SAL09]), [])
        self.assertEqual(self.sell_opens([SAL09, SAL09_B]), [])                # every copy of a reserved ref

    def test_an_open_sell_thread_is_closed(self):
        acts = self.moves([SAL09])
        self.assertEqual([a.kind for a in acts], ["close_thread"])
        self.assertIn("reserved_refs", acts[0].reason)


class PageGoal(Patched):
    building = {"SAL"}

    def test_the_only_copy_of_a_page_we_build_stays(self):
        self.assertEqual(self.sell_opens([SAL09]), [])
        self.assertEqual([a.kind for a in self.moves([SAL09])], ["close_thread"])

    def test_a_real_spare_may_go(self):
        self.assertTrue(self.sell_opens([SAL09, SAL09_B]))


class BrainOrder(Patched):
    reserved = {"SAL-09"}
    building = {"SAL"}
    orders = [{"dealer": "chato", "action": "sell", "ref": "SAL-09", "open": 100, "bound": 72, "max_messages": 8,
               "why": "the brain decided this sale"}]

    def test_the_brains_own_sell_order_still_runs(self):
        acts = self.moves([SAL09])
        self.assertTrue(acts)
        self.assertNotIn("close_thread", [a.kind for a in acts])


class SecondCopy(Patched):
    def buys(self, assets):
        dom = T.domain()
        plan = dom._prepare(SIT(tick=5, assets=[dict(a) for a in assets]), CTX(5))
        return {c.item for c in plan.candidates if c.kind.startswith("buy") and not c.kind.endswith("pack")}

    def test_the_code_opens_no_buy_for_a_card_we_hold(self):
        held = {"id": 30, "kind": "card", "ref": "LAV-07", "rarity": "uncommon", "set": "LAV", "your_value": 146.0}
        without = self.buys([])
        self.assertIn("LAV-07", without)                 # the fixture does offer it when we do not hold it
        self.assertNotIn("LAV-07", self.buys([held]))


if __name__ == "__main__":
    unittest.main()
