"""Sunday's duels: 12 ticks, decay 0.10, price + days, four live at once, 15 s ticks.

What must hold whatever Claude does: every live duel gets an answer in its first tick, no price ever crosses
our limit, and a restart in the middle of a session keeps the duel's clock.
"""
from __future__ import annotations

import random
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.duels import sunday_eval as se
from bazaar.duels.domain import DuelsDomain
from bazaar.duels.model import MIN_SURPLUS, surplus
from bazaar.duels.opponent import OpponentMemory
from bazaar.duels.policy import PARAMS


def mem(path=None, autosave=False) -> OpponentMemory:
    return OpponentMemory(path or Path(tempfile.mkdtemp()) / "m.json", autosave=autosave)


def duel(i: int, role: str, limit: int, tick: int = 2000, **kw) -> dict:
    d = {"duel": i, "session": 4, "status": "live", "role": role, "item": f"Item {i}", "issues": ["price", "days"],
         "your_days_weight": 2.5, "days_meaning": se.SELLER_DAYS if role == "seller" else se.BUYER_DAYS,
         "your_limit": limit, "rival": f"Rival {i}", "deadline_tick": tick + 12, "decay_per_round": 0.1, "rounds": 0,
         "your_offer": None, "rival_offer": None, "messages": [], "result": None, "price": None, "days": None}
    d.update(kw)
    return d


def ctx(**kw):
    base = dict(tick=2000, deadline=None, budget={}, lessons=None, llm=None, llm_ok=True, tick_seconds=15.0)
    base.update(kw)
    return SimpleNamespace(**base)


class LLM:
    """A Claude that is late, fails, or answers with a fixed move."""

    def __init__(self, move=None, delay=0.0, fail=False):
        self.move, self.delay, self.fail, self.calls = move, delay, fail, 0
        self.lock = threading.Lock()

    def ask(self, **kw):
        with self.lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("api down")
        calls = [] if self.move is None else [{"name": "duel_move", "input": dict(self.move)}]
        return SimpleNamespace(text="", tool_calls=calls, model="fake", key="A", usage={}, cost_usd=0.0,
                               latency_s=self.delay)


FOUR = [duel(1, "seller", 80), duel(2, "buyer", 120), duel(3, "seller", 45), duel(4, "buyer", 160)]


class FourLiveDuelsAnswerInTheirFirstTick(unittest.TestCase):
    def check(self, acts):
        self.assertEqual(sorted(a.params["duel"] for a in acts), [1, 2, 3, 4])
        for a, d in zip(sorted(acts, key=lambda a: a.params["duel"]), FOUR):
            self.assertEqual(a.kind, "duel_message")
            self.assertGreaterEqual(surplus(d["role"], d["your_limit"], a.params["price"]), MIN_SURPLUS)
            self.assertIn(a.params["days"], range(11))

    def test_claude_slower_than_the_tick(self):
        dom = DuelsDomain(memory=mem(), llm=LLM({"action": "wait", "price": 0, "days": 0, "text": "", "reason": "",
                                                 "expected_points": 0}, delay=1.5))
        t0 = time.time()
        acts = dom.decide(SimpleNamespace(tick=2000, duels=FOUR), ctx(deadline=time.time() + 0.5))
        self.assertLess(time.time() - t0, 0.9)             # we did not wait for it
        self.check(acts)
        self.assertTrue(all(a.source == "fallback" for a in acts))

    def test_claude_down(self):
        dom = DuelsDomain(memory=mem(), llm=LLM(fail=True))
        self.check(dom.decide(SimpleNamespace(tick=2000, duels=FOUR), ctx(deadline=time.time() + 2)))

    def test_claude_answers_nothing_usable(self):
        dom = DuelsDomain(memory=mem(), llm=LLM(None))
        self.check(dom.decide(SimpleNamespace(tick=2000, duels=FOUR), ctx(deadline=time.time() + 2)))

    def test_breaker_open(self):
        dom = DuelsDomain(memory=mem(), llm=LLM(fail=True))
        self.check(dom.decide(SimpleNamespace(tick=2000, duels=FOUR), ctx(deadline=time.time() + 2, llm_ok=False)))
        self.assertEqual(dom._llm.calls, 0)

    def test_claude_asks_for_a_price_outside_every_limit(self):
        dom = DuelsDomain(memory=mem(), llm=LLM({"action": "offer", "price": 1, "days": 99, "text": "1 P",
                                                 "reason": "", "expected_points": 0}))
        self.check(dom.decide(SimpleNamespace(tick=2000, duels=FOUR), ctx(deadline=time.time() + 2)))


class TheLimitIsNeverCrossed(unittest.TestCase):
    def test_every_rival_kind_on_sundays_format(self):
        """Every price we send and every deal we close leaves us at least MIN_SURPLUS, both roles."""
        for kind in se.RIVALS:
            rng = random.Random(kind)
            dom = DuelsDomain(memory=mem(), use_llm=False)
            for i in range(40):
                sc = se.scenario(rng, "seller" if i % 2 == 0 else "buyer", 0.10)
                r = se.run_duel(dom, sc, se.RIVALS[kind](sc, random.Random(rng.random())), i + 1, f"R{kind}{i}", 12,
                                3000 + 20 * i)
                self.assertFalse(r.illegal, (kind, i, r.price))
                for m in r.log:
                    if m["from"] == "you":
                        self.assertGreaterEqual(surplus(sc.our_role, sc.our_limit, m["price"]), MIN_SURPLUS, (kind, m))
                if r.deal:
                    self.assertGreaterEqual(surplus(sc.our_role, sc.our_limit, r.price), MIN_SURPLUS, (kind, r.price))

    def test_a_claude_that_accepts_everything_cannot_cross_it(self):
        llm = LLM({"action": "accept", "price": 0, "days": 0, "text": "", "reason": "", "expected_points": 0})
        dom = DuelsDomain(memory=mem(), llm=llm)
        # the rival asks 200 for something worth 120 to us (buyer), and offers 10 to a seller whose cost is 80
        bad_buy = duel(2, "buyer", 120, rival_offer={"id": 9, "price": 200, "tick": 2000, "days": 0},
                       messages=[{"tick": 2000, "from": "Rival 2", "text": "200", "price": 200, "days": 0}])
        bad_sell = duel(1, "seller", 80, rival_offer={"id": 8, "price": 10, "tick": 2000, "days": 10},
                        messages=[{"tick": 2000, "from": "Rival 1", "text": "10", "price": 10, "days": 10}])
        acts = dom.decide(SimpleNamespace(tick=2000, duels=[bad_sell, bad_buy]), ctx(deadline=time.time() + 2))
        self.assertFalse([a for a in acts if a.kind == "duel_accept"])


class RestartInTheMiddleOfASession(unittest.TestCase):
    def test_the_duel_keeps_its_twelve_ticks(self):
        path = Path(tempfile.mkdtemp()) / "duel_memory.json"
        a = DuelsDomain(memory=mem(path, autosave=True), use_llm=False)
        first = a.fallback(SimpleNamespace(tick=2000, duels=[duel(1, "seller", 80)]), ctx())
        opening = first[0].params["price"]
        a.memory.save()
        # the bot restarts; six ticks later the duel is still live with our opening on the table
        b = DuelsDomain(memory=mem(path, autosave=True), use_llm=False)
        live = duel(1, "seller", 80, your_offer={"id": 1, "price": opening, "tick": 2000, "days": 10},
                    messages=[{"tick": 2000, "from": "you", "text": "", "price": opening, "days": 10}])
        v = b._views(SimpleNamespace(tick=2006, duels=[live]), ctx(tick=2006))[0]
        self.assertEqual(v.total_ticks, 12)
        self.assertEqual(v.elapsed, 6)
        # and the silent rival still gets no second message before the last ticks
        self.assertEqual(b.fallback(SimpleNamespace(tick=2006, duels=[live]), ctx(tick=2006)), [])

    def test_with_no_memory_at_all_it_still_plays_inside_the_limit(self):
        b = DuelsDomain(memory=mem(), use_llm=False)
        live = duel(2, "buyer", 120, rival_offer={"id": 9, "price": 150, "tick": 2005, "days": 10},
                    messages=[{"tick": 2005, "from": "Rival 2", "text": "150", "price": 150, "days": 10}])
        for a in b.fallback(SimpleNamespace(tick=2006, duels=[live]), ctx(tick=2006)):
            self.assertNotEqual(a.kind, "duel_accept")
            self.assertLessEqual(a.params["price"], 120 - MIN_SURPLUS)


class TheEvaluationTool(unittest.TestCase):
    def test_variants_leave_the_live_parameters_untouched(self):
        before = dict(PARAMS)
        se.with_params({"OPEN": 0.5, "LAST_TICKS": 5}, lambda: self.assertEqual(PARAMS["OPEN"], 0.5))
        self.assertEqual(PARAMS, before)

    def test_it_scores_like_the_server(self):
        res = se.play(20, 3, 12, 0.10, ["mirror", "silent"])
        self.assertEqual(res["silent"]["points"], 0.0)          # nobody answers: nothing to score
        self.assertGreater(res["mirror"]["deal_rate"], 0.8)     # two copies of our policy close
        self.assertEqual(res["mirror"]["illegal"], 0)


if __name__ == "__main__":
    unittest.main()
