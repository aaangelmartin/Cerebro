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

    def test_four_live_duels_can_all_accept_in_one_tick(self):
        """Sunday runs four duels at once with one shared deadline: the last tick must not drop the fourth."""
        from bazaar.core.arbiter import select
        from types import SimpleNamespace as NS
        b = self.budget()
        d = b.for_tick(5, LIMITS, now=0)
        self.assertEqual(d["duel_accepts_left"], 4)
        duels = [Action("duel_accept", {"duel": i, "expect": {}}, "duels", priority=150 + i) for i in (1, 2, 3, 4)]
        sit = NS(tick=5, limits=dict(LIMITS), threads=[], my_offers=[], duels=[], me={"cash": 300, "assets": []})
        chosen, dropped = select(duels, sit, {"accepts_left": 1, "messages": {}, "offers_left": 12})
        self.assertEqual((len(chosen), dropped), (4, []))
        for a in duels:
            self.assertTrue(rails.rail_pace(a, {"limits": LIMITS}, {"budget": d}).ok)
            b.record(a, "sent", now=0)
            d = b.for_tick(5, LIMITS, now=0)
        self.assertFalse(rails.rail_pace(Action("duel_accept", {"duel": 5}, "duels"), {"limits": LIMITS}, {"budget": d}).ok)


if __name__ == "__main__":
    unittest.main()
