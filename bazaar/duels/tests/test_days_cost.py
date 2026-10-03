"""Duels II: when delivery days cost us we do not hand them out (sim duel 1168 burned 23 of 34 P on 10 days)."""
from __future__ import annotations

import unittest

from bazaar.duels.model import DAYS_MAX, parse_duel
from bazaar.duels.policy import choose_days, plan
from bazaar.duels.tests.test_duels import duel, mem

VALUE = "value to you of each delivery day"


def view(w, rival_days, n=3, meaning=VALUE):
    """Buyer, limit 143; the rival made `n` offers, stepping 4 P down, always with `rival_days` days."""
    ms, prices = [], [140 - 4 * i for i in range(n)]
    for i, p in enumerate(prices):
        ms.append({"tick": 100 + 2 * i, "from": "Rival Oro", "text": "", "price": p, "days": rival_days})
        ms.append({"tick": 101 + 2 * i, "from": "you", "text": "", "price": 100 + i, "days": 0})
    last = {"id": n, "price": prices[-1], "days": rival_days, "tick": 100 + 2 * (n - 1)}
    return parse_duel(duel(issues=["price", "days"], your_days_weight=w, days_meaning=meaning,
                           decay_per_round=0.08, rival_offer=last, messages=ms[:-1]), 100 + 2 * (n - 1))


class TestDaysCostUs(unittest.TestCase):
    def test_rival_insisting_on_ten_days_gets_none(self):
        v = view(-2.3, DAYS_MAX)
        self.assertFalse(v.days_ambiguous)
        self.assertLess(v.days_w, 0)
        self.assertEqual(choose_days(v, pie=34), 0)
        self.assertEqual(choose_days(v), 0)

    def test_plan_offers_zero_days_when_they_cost(self):
        v = view(-2.3, DAYS_MAX)
        mv = plan(v, mem().assess(v))
        if mv.action == "offer":
            self.assertEqual(mv.days, 0)
        elif mv.action == "accept":           # accepting their 10 days must still pay for those days
            self.assertGreater(v.utility(mv.price, mv.days), 0)

    def test_cheap_goodwill_matches_rivals_low_days(self):
        v = view(-0.5, 2)
        self.assertEqual(choose_days(v, pie=40), 2)        # 1 P < 10 % of 40
        self.assertEqual(choose_days(v, pie=8), 0)         # 1 P >= 0.8

    def test_cost_wording_with_positive_weight_counts_as_cost(self):
        v = view(2.3, DAYS_MAX, meaning="cost per delivery day")
        self.assertLess(v.days_w, 0)
        self.assertEqual(choose_days(v, pie=34), 0)


class TestDaysHelpUs(unittest.TestCase):
    def test_rival_also_wants_days_gets_max(self):
        self.assertEqual(choose_days(view(2.0, DAYS_MAX), pie=34), DAYS_MAX)

    def test_positive_weight_plan_counts_days_as_value(self):
        v = view(2.0, DAYS_MAX)
        mv = plan(v, mem().assess(v))
        if mv.action == "offer":
            self.assertEqual(mv.days, DAYS_MAX)


if __name__ == "__main__":
    unittest.main()
