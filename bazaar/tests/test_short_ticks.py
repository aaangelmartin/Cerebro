"""Sunday runs on 15 s ticks: deadlines follow the clock in real seconds, the recorder keeps inside its request
budget, and a duel is answered on its first tick whatever the model does."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar import config, run
from bazaar.core import state
from bazaar.duels.domain import DuelsDomain
from bazaar.duels.tests.test_duels import ctx, duel, mem
from bazaar.llm.client import LLMTimeout
from bazaar.recorder import core as rcore
from bazaar.recorder.tests.test_recorder import FakeAPI, make


class DeadlineTest(unittest.TestCase):
    def test_short_tick_gets_a_larger_share_and_long_ticks_keep_theirs(self):
        self.assertEqual(state.decision_share(30.0), config.DECISION_DEADLINE)
        self.assertEqual(state.decision_share(60.0), config.DECISION_DEADLINE)
        self.assertEqual(state.decision_share(15.0), state.SHORT_TICK_DEADLINE)
        self.assertEqual(state.decision_share(0.2), config.DECISION_DEADLINE)      # simulator and tests: unchanged
        left_to_send = 15.0 * (1 - state.decision_share(15.0))
        self.assertGreaterEqual(left_to_send, 5.0)                                 # room to send before the tick ends

    def test_perceive_puts_the_deadline_at_the_short_tick_share(self):
        class GW:
            def get(self, path, timeout=None, **params):
                return {}

        live = Path(tempfile.mkdtemp(prefix="short-tick-"))
        t0 = 1000.0
        clock = {"tick": 2000, "t_hours": 15.0, "tick_seconds": 15.0, "next_tick_in": 15.0, "doors": "open"}
        sit = state.perceive(GW(), None, live=live, now=t0, clock=clock)
        self.assertEqual(sit.tick_seconds, 15.0)
        self.assertAlmostEqual(sit.deadline - sit.tick_start, 15.0 * state.SHORT_TICK_DEADLINE)
        sat = state.perceive(GW(), None, live=live, now=t0, clock={**clock, "tick_seconds": 30.0, "next_tick_in": 30.0})
        self.assertAlmostEqual(sat.deadline - sat.tick_start, 30.0 * config.DECISION_DEADLINE)


class StuckTest(unittest.TestCase):
    def test_patience_is_real_seconds(self):
        self.assertEqual(run.stuck_ticks(30.0), 3)          # Saturday: 90 s
        self.assertEqual(run.stuck_ticks(15.0), 6)          # Sunday: still 90 s, not 45
        self.assertEqual(run.stuck_ticks(60.0), 3)          # never fewer than STUCK_TICKS
        self.assertEqual(run.stuck_ticks(0.2), 3)           # simulator and tests
        self.assertEqual(run.stuck_ticks(None), 3)


class RecorderTest(unittest.TestCase):
    VENUES = {"venues": [{"venue": f"v{i:02d}", "trades": 0} for i in range(1, 13)]}

    def books(self, tick_seconds):
        rec = make(Path(tempfile.mkdtemp(prefix="rec-short-")), FakeAPI())
        rec.clock = {"tick": 30, "tick_seconds": tick_seconds, "doors": "open"}
        rec.tick = 30
        rec.on_venues(self.VENUES)
        return [j.key for j in rec.queues["public"] if j.key.startswith("book:")]

    def test_short_ticks_read_the_books_on_the_rota(self):
        full = self.books(30.0)
        short = self.books(15.0)
        self.assertEqual(len(full), 13)                                  # twelve venues and El Rastro, every tick
        self.assertIn("book:rastro", short)                              # El Rastro is always read
        self.assertLessEqual(len(short), 1 + 12 // rcore.BOOK_SQUEEZED_EVERY + 1)
        self.assertLess(len(short), len(full))


class SlowLLM:
    """A model that never answers in time."""

    def __init__(self):
        self.calls = 0

    def ask(self, **kw):
        self.calls += 1
        raise LLMTimeout("slow")

    def race(self, *, models, **kw):
        self.calls += 1
        raise LLMTimeout("slow")


class DuelFirstTickTest(unittest.TestCase):
    def test_code_answers_the_first_tick_when_the_model_is_late(self):
        llm = SlowLLM()
        dom = DuelsDomain(memory=mem(), llm=llm)
        d = duel()
        acts = dom.decide(SimpleNamespace(tick=100, duels=[d]), ctx(tick_seconds=15, deadline=time.time() + 8))
        self.assertEqual(llm.calls, 1)
        self.assertEqual(len(acts), 1)                                   # the duel is answered on its first tick
        a = acts[0]
        self.assertIn(a.kind, ("duel_offer", "duel_accept", "duel_message"))
        self.assertEqual(a.source, "fallback")
        price = (a.params or {}).get("price")
        if price is not None:                                            # never across our own limit
            lim = d.get("your_limit") or d.get("limit")
            if d.get("role") == "seller":
                self.assertGreaterEqual(price, lim)
            else:
                self.assertLessEqual(price, lim)


if __name__ == "__main__":
    unittest.main()


class DealerHourTest(unittest.TestCase):
    def test_a_dealer_out_of_budget_waits_one_game_hour_at_any_tick_length(self):
        from bazaar.dealers.domain import BUDGET_BLOCK_TICKS, budget_block_ticks
        self.assertEqual(budget_block_ticks(30.0), 120)
        self.assertEqual(budget_block_ticks(15.0), 240)          # Sunday: an hour is 240 ticks
        self.assertEqual(budget_block_ticks(60.0), 60)
        self.assertEqual(budget_block_ticks(0.05), BUDGET_BLOCK_TICKS)      # the simulator's fast clock
        self.assertEqual(budget_block_ticks(None), BUDGET_BLOCK_TICKS)
