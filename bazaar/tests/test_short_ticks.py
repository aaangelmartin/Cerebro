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


class SlowDomainShareTest(unittest.TestCase):
    """Dealers and market start their model call after the reads, so on short ticks they get a little longer;
    duels keep the common share, and so does everybody while a duel is live."""

    def test_only_the_slow_domains_get_the_longer_share_and_never_with_a_live_duel(self):
        self.assertEqual(state.domain_share("dealers", 15.0), state.SLOW_DOMAIN_DEADLINE)
        self.assertEqual(state.domain_share("market", 15.0), state.SLOW_DOMAIN_DEADLINE)
        self.assertEqual(state.domain_share("duels", 15.0), state.SHORT_TICK_DEADLINE)
        self.assertEqual(state.domain_share("dealers", 15.0, live_duels=True), state.SHORT_TICK_DEADLINE)
        self.assertEqual(state.domain_share("dealers", 30.0), config.DECISION_DEADLINE)     # Saturday's ticks
        self.assertLess(state.SLOW_DOMAIN_DEADLINE, run.SEND_CUTOFF - 0.15)                 # room to send

    def _run(self, name, delay, duels=()):
        from bazaar.core.types import Action
        from bazaar.tests.test_run import Dom, Exe, FakeGateway, Led, rails_ok
        tmp = Path(tempfile.mkdtemp())
        (tmp / "control.json").write_text('{"armed": true}')
        think = Action("thread_message", {"thread": 1, "price": 9}, name, source="opus")
        code = Action("close_thread", {"thread": 1}, name, source="fallback")
        exe = Exe()
        r = run.Runner(FakeGateway(), domains=[Dom(name, [think], delay=delay, fb=[code])], mode="sim", live=tmp,
                       make_write_gw=lambda: "W", ledger=Led(), rails=rails_ok(), executor=exe)
        now = time.time()
        sit = state.Situation(tick=5, day="sun", tick_seconds=5.0, tick_start=now, duels=list(duels),
                              deadline=now + 5.0 * state.decision_share(5.0),
                              me={"id": "t10", "cash": 300, "collection_value": 700.0, "score": {"score": 20.0}})
        r.step(sit)
        return [a.kind for a in exe.sent], time.time() - now

    def test_a_dealer_answer_just_after_the_common_deadline_is_still_used(self):
        late = 5.0 * (state.SHORT_TICK_DEADLINE + state.SLOW_DOMAIN_DEADLINE) / 2        # between the two deadlines
        sent, took = self._run("dealers", late)
        self.assertEqual(sent, ["thread_message"])
        self.assertLess(took, 5.0 * run.SEND_CUTOFF)

    def test_duels_and_a_tick_with_a_live_duel_keep_the_common_deadline(self):
        late = 5.0 * (state.SHORT_TICK_DEADLINE + state.SLOW_DOMAIN_DEADLINE) / 2
        self.assertEqual(self._run("duels", late)[0], ["close_thread"])                  # the code's answer goes out
        sent, took = self._run("dealers", late, duels=[{"id": 9, "status": "live"}])
        self.assertEqual(sent, ["close_thread"])
        self.assertLess(took, 5.0 * state.SHORT_TICK_DEADLINE + 0.4)                     # nobody waited longer

    def test_past_its_own_deadline_the_code_answers(self):
        sent, took = self._run("dealers", 5.0 * state.SLOW_DOMAIN_DEADLINE + 0.4)
        self.assertEqual(sent, ["close_thread"])
        self.assertLess(took, 5.0 * run.SEND_CUTOFF)
