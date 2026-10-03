import tempfile
import unittest
from pathlib import Path

from bazaar.core import rails
from bazaar.core.context import Budget
from bazaar.core.types import Action

LIMITS = {"accepts_per_team_per_tick": 1}


class AcceptBudgetsTest(unittest.TestCase):
    def budget(self):
        return Budget(Path(tempfile.mkdtemp()) / "budget.json")

    def test_duel_accept_keeps_the_trade_slot_free(self):
        b = self.budget()
        b.for_tick(5, LIMITS, now=0)
        b.record(Action("duel_accept", {"duel": 9}, "duels"), "sent", now=0)
        d = b.for_tick(5, LIMITS, now=0)
        self.assertEqual((d["accepts_left"], d["duel_accepts_used"]), (1, 1))
        ctx = {"budget": d}
        self.assertTrue(rails.rail_pace(Action("accept_offer", {"offer": 1}, "market"), {"limits": LIMITS}, ctx).ok)

    def test_trade_accept_keeps_duel_accepts_free(self):
        b = self.budget()
        b.for_tick(5, LIMITS, now=0)
        b.record(Action("accept_offer", {"offer": 1}, "market"), "sent", now=0)
        d = b.for_tick(5, LIMITS, now=0)
        self.assertEqual(d["accepts_left"], 0)
        ctx = {"budget": d}
        self.assertFalse(rails.rail_pace(Action("accept_offer", {"offer": 2}, "market"), {"limits": LIMITS}, ctx).ok)
        self.assertTrue(rails.rail_pace(Action("duel_accept", {"duel": 9}, "duels"), {"limits": LIMITS}, ctx).ok)

    def test_duel_accept_limit_and_reset(self):
        b = self.budget()
        lim = {**LIMITS, "duel_accepts_per_team_per_tick": 1}
        b.for_tick(5, lim, now=0)
        b.record(Action("duel_accept", {"duel": 9}, "duels"), "sent", now=0)
        d = b.for_tick(5, lim, now=0)
        self.assertFalse(rails.rail_pace(Action("duel_accept", {"duel": 8}, "duels"), {"limits": lim}, {"budget": d}).ok)
        self.assertEqual(b.for_tick(6, lim, now=0)["duel_accepts_left"], 1)


if __name__ == "__main__":
    unittest.main()
