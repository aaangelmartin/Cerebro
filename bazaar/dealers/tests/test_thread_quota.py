"""code-f4b9b563: the conversations-per-hour quota of a dealer is tracked and spent on the orders worth most."""
from __future__ import annotations

import time
import unittest

from bazaar.core.types import Outcome
from bazaar.dealers import profiles
from bazaar.dealers.evaluate import make_ctx
from bazaar.dealers.tests.test_brain_orders import PILAR, SAL08, domain, order, sit

SAL04 = {"id": 9, "kind": "card", "ref": "SAL-04", "rarity": "uncommon", "set": "SAL", "your_value": 3}


def opens(dom, assets):
    return [a for a in dom.fallback(sit(assets), make_ctx(5)) if a.kind == "open_thread"]


class QuotaTest(unittest.TestCase):
    def test_opened_threads_are_counted_in_a_rolling_hour(self):
        dom, _ = domain([])
        dom.store.note_open("pilar", now=time.time() - 4000)          # older than an hour: dropped
        for _ in range(3):
            dom.store.note_open("pilar")
        self.assertEqual(dom.store.opens_last_hour("pilar"), 3)
        self.assertEqual(dom.store.quota_left("pilar", 6), 6)         # no deals yet, 7 conversations left
        self.assertEqual(profiles.quota_left(dom.store.data, "pilar", 20), 7)

    def test_a_sent_open_counts_and_the_refusal_teaches_the_number(self):
        dom, _ = domain([order()])
        a = opens(dom, [dict(SAL08)])[0]
        dom.observe(Outcome(action_id=a.id, tick=5, status="sent", response={}))
        self.assertEqual(dom.store.opens_last_hour("pilar"), 1)
        b = opens(dom, [dict(SAL08)])[0]
        dom.observe(Outcome(action_id=b.id, tick=6, status="refused",
                            response={"error": "at most 4 conversations per hour with pilar"}))
        self.assertEqual(dom.store.conv_quota("pilar"), 4)
        self.assertTrue(dom.store.quota_blocked("pilar"))

    def test_no_thread_once_the_conversations_are_used_up(self):
        dom, notes = domain([order()])
        for _ in range(profiles.CONV_QUOTA):
            dom.store.note_open("pilar")
        self.assertEqual(opens(dom, [dict(SAL08)]), [])
        plan = dom._prepare(sit([dict(SAL08)]), make_ctx(5))
        self.assertEqual(plan.quota_left["pilar"], 0)
        self.assertIn("hourly quota", notes[0][2])

    def test_the_order_worth_most_opens_first(self):
        dom, _ = domain([order(ref="SAL-04", open=5, bound=4), order()])   # cheap card listed first by the brain
        out = opens(dom, [dict(SAL04), dict(SAL08)])
        self.assertEqual(out[0].params["topic"], {"sell": {"assets": [7]}})  # SAL-08 (30 vs value 22.5) goes first

    def test_own_candidates_do_not_eat_the_quota_of_a_waiting_order(self):
        # one thread left with Pilar and a brain order that cannot start this tick (card not held yet)
        spare = [{"id": 1, "kind": "card", "ref": "SAL-07", "rarity": "uncommon", "set": "SAL", "your_value": 2},
                 {"id": 2, "kind": "card", "ref": "SAL-07", "rarity": "uncommon", "set": "SAL", "your_value": 2}]
        dom, _ = domain([])
        self.assertTrue([c for c in dom._prepare(sit(spare), make_ctx(5)).candidates if c.dealer == "pilar"])
        dom, _ = domain([order()])
        for _ in range(profiles.CONV_QUOTA - 1):
            dom.store.note_open("pilar")
        plan = dom._prepare(sit(spare), make_ctx(5))
        self.assertEqual(plan.quota_left["pilar"], 1)
        self.assertEqual([c for c in plan.candidates if c.dealer == "pilar"], [])


if __name__ == "__main__":
    unittest.main()
