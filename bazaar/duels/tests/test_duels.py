"""Duel negotiator: model, guard, fallback against fake rivals, opponent memory, Claude path, injection."""
from __future__ import annotations

import json
import random
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar import config
from bazaar.duels.domain import DuelsDomain
from bazaar.duels.model import MIN_SURPLUS, parse_duel, points
from bazaar.duels.opponent import OpponentMemory
from bazaar.duels.policy import Move, guard, plan
from bazaar.duels.prompt import DUEL_MOVE_TOOL, SYSTEM
from bazaar.duels.simulator import INJECTIONS, RIVALS, Scenario, make_scenario, run_duel
from bazaar.duels.tournament import play


def mem() -> OpponentMemory:
    return OpponentMemory(Path(tempfile.mkdtemp()) / "m.json", autosave=False)


def duel(**kw) -> dict:
    d = {"duel": 7, "session": 2, "status": "live", "role": "buyer", "item": "Andén 0", "issues": ["price"],
         "your_days_weight": None, "days_meaning": None, "your_limit": 143, "rival": "Rival Oro",
         "deadline_tick": 116, "decay_per_round": 0.06, "rounds": 0, "your_offer": None, "rival_offer": None,
         "messages": [], "result": None, "price": None, "days": None}
    d.update(kw)
    return d


def ctx(**kw):
    base = dict(tick=100, deadline=None, budget={}, lessons=None, llm=None, llm_ok=True)
    base.update(kw)
    return SimpleNamespace(**base)


class FakeLLM:
    """Records prompts; returns a fixed duel_move (optionally after a delay)."""

    def __init__(self, move: dict | None, delay: float = 0.0):
        self.move, self.delay, self.prompts = move, delay, []
        self.lock = threading.Lock()

    def ask(self, **kw):
        with self.lock:
            self.prompts.append(kw)
        if self.delay:
            time.sleep(self.delay)
        calls = [] if self.move is None else [{"name": "duel_move", "input": dict(self.move)}]
        return SimpleNamespace(text="", tool_calls=calls, model="fake", key="A", usage={}, cost_usd=0.0,
                               latency_s=self.delay)


class TestModel(unittest.TestCase):
    def test_points_formula_matches_friday(self):
        # docs/LOG.md: duel 211 buyer limit 151, price 114, 1 round -> 34.8; duel 257 -> 24.1
        self.assertAlmostEqual(points(151 - 114, 0.06, 1), 34.78, places=2)
        self.assertAlmostEqual(points(132 - 103, 0.06, 3), 24.09, places=2)

    def test_parse_real_friday_duels(self):
        data = json.loads((config.FRIDAY / "analysis" / "duels.json").read_text())
        views = [parse_duel(d, 160) for d in data["duels"]]
        self.assertTrue(all(views))
        v = next(x for x in views if x.id == 248)
        self.assertEqual((v.role, v.limit, v.rival_offer.price, v.our_offer.price), ("buyer", 143, 146, 134))
        self.assertEqual(len(v.rival_msgs()), 2)
        self.assertEqual(v.ticks_left, 8)

    def test_rounds_prediction(self):
        v = parse_duel(duel(messages=[{"tick": 100, "from": "Rival Oro", "text": "", "price": 150}],
                            rival_offer={"id": 1, "price": 150, "tick": 100}), 100)
        self.assertTrue(v.unanswered_rival_offer())
        self.assertEqual(v.rounds_if_we_send(), 1)     # countering a fresh offer costs a round
        v2 = parse_duel(duel(messages=[{"tick": 100, "from": "you", "text": "", "price": 110}],
                             your_offer={"id": 1, "price": 110, "tick": 100}), 101)
        self.assertEqual(v2.rounds_if_we_send(), 0)    # they owe us an answer: a new offer is free


class TestGuard(unittest.TestCase):
    def test_fuzz_never_outside_limit(self):
        rng = random.Random(3)
        for _ in range(500):
            role = rng.choice(["buyer", "seller"])
            lim = rng.randint(20, 200)
            days = rng.random() < 0.5
            ro = rng.randint(1, 400)
            d = duel(role=role, your_limit=lim, issues=["price", "days"] if days else ["price"],
                     your_days_weight=rng.uniform(-3, 3) if days else None,
                     rival_offer={"id": 9, "price": ro, "tick": 100, "days": rng.randint(0, 10)},
                     messages=[{"tick": 100, "from": "Rival Oro", "text": "x", "price": ro,
                                "days": rng.randint(0, 10) if days else None}])
            v = parse_duel(d, 100)
            mv = Move(rng.choice(["accept", "offer", "wait", "bogus"]), price=rng.randint(-50, 500),
                      days=rng.randint(-5, 15), text=rng.choice(["", "deal at 5 P", "hello"]))
            safe, _ = guard(v, mv, fallback=Move("wait"))
            if safe.action in ("accept", "offer"):
                self.assertGreaterEqual(v.surplus(safe.price), MIN_SURPLUS)
                if days:
                    self.assertTrue(0 <= safe.days <= 10)
            if safe.action == "accept":
                self.assertEqual(safe.price, v.rival_offer.price)
                self.assertGreaterEqual(v.utility(safe.price, safe.days), MIN_SURPLUS)
            if safe.action == "offer":
                self.assertIn(str(safe.price), safe.text)

    def test_no_repeat_of_standing_offer(self):
        v = parse_duel(duel(your_offer={"id": 1, "price": 110, "tick": 99},
                            messages=[{"tick": 99, "from": "you", "text": "", "price": 110}]), 100)
        safe, notes = guard(v, Move("offer", price=110, text="110 P"))
        self.assertEqual(safe.action, "wait")

    def test_offer_worse_than_rival_becomes_accept(self):
        v = parse_duel(duel(rival_offer={"id": 4, "price": 100, "tick": 100},
                            messages=[{"tick": 100, "from": "Rival Oro", "text": "", "price": 100}]), 100)
        safe, _ = guard(v, Move("offer", price=105, text="105"))
        self.assertEqual((safe.action, safe.price), ("accept", 100))

    def test_text_without_exact_price_gets_template(self):
        v = parse_duel(duel(), 100)
        safe, _ = guard(v, Move("offer", price=90, text="How about ninety? Or 95 P?"))
        self.assertIn("90", safe.text)
        self.assertNotIn("95", safe.text)


class TestFallbackVsRivals(unittest.TestCase):
    def test_every_rival_type(self):
        rng = random.Random(5)
        for kind, cls in RIVALS.items():
            res = []
            for i in range(40):
                sc = make_scenario(rng, days=(kind == "days"))
                d = DuelsDomain(memory=mem(), use_llm=False)
                r = run_duel(d, sc, cls(sc, random.Random(i)), i, f"Rival {kind}")
                self.assertFalse(r.illegal, kind)
                res.append(r)
            deal = sum(r.deal for r in res) / len(res)
            avg = sum(r.points for r in res) / len(res)
            floor = {"tough": 0.4, "mute": 0.5}.get(kind, 0.85)
            self.assertGreaterEqual(deal, floor, f"{kind}: deal rate {deal:.2f}")
            self.assertGreaterEqual(avg, 0.0, kind)

    def test_fixed_rival_closes_fast(self):
        sc = Scenario(value=150, cost=100, our_role="buyer")
        r = run_duel(DuelsDomain(memory=mem(), use_llm=False), sc, RIVALS["fixed"](sc, random.Random(1)), 1, "Rival Plata")
        self.assertTrue(r.deal)
        self.assertLessEqual(r.rounds, 2)

    def test_accepts_are_big_and_high_priority(self):
        d = duel(rival_offer={"id": 4, "price": 60, "tick": 100},
                 messages=[{"tick": 100, "from": "Rival Oro", "text": "", "price": 60}])
        acts = DuelsDomain(memory=mem(), use_llm=False).fallback(SimpleNamespace(tick=100, duels=[d]), ctx())
        self.assertEqual(acts[0].kind, "duel_accept")
        self.assertTrue(acts[0].big)
        self.assertGreaterEqual(acts[0].priority, 100)
        self.assertEqual(acts[0].params["expect"]["price"], 60)
        self.assertAlmostEqual(acts[0].expected["points"], 83.0)

    def test_days_param_only_in_duels_ii(self):
        dom = DuelsDomain(memory=mem(), use_llm=False)
        a1 = dom.fallback(SimpleNamespace(tick=100, duels=[duel()]), ctx())
        self.assertNotIn("days", a1[0].params)
        d2 = duel(duel=8, issues=["price", "days"], your_days_weight=2.0, decay_per_round=0.08)
        a2 = dom.fallback(SimpleNamespace(tick=100, duels=[d2]), ctx())
        self.assertIn(a2[0].params["days"], range(0, 11))

    def test_one_message_per_tick(self):
        d = duel(messages=[{"tick": 100, "from": "you", "text": "", "price": 100}],
                 your_offer={"id": 1, "price": 100, "tick": 100})
        self.assertEqual(DuelsDomain(memory=mem(), use_llm=False).fallback(
            SimpleNamespace(tick=100, duels=[d]), ctx()), [])


class TestOpponentMemory(unittest.TestCase):
    def test_second_leg_uses_first_leg_limit(self):
        m = mem()
        # Leg 1: we sold "Plaza" with cost 80.
        m.observe_duel(parse_duel(duel(duel=1, role="seller", item="Plaza", your_limit=80), 100))
        # Leg 2: we buy "Plaza" with value 130: the rival's cost is very likely 80 -> pie 50.
        v = parse_duel(duel(duel=2, role="buyer", item="Plaza", your_limit=130, rival="Rival Sol"), 120)
        a = m.assess(v)
        self.assertEqual(a["rival_limit_estimate"], 80)
        self.assertEqual(a["pie_estimate"], 50)
        # A rival offer below that cost contradicts it: dropped.
        v2 = parse_duel(duel(duel=2, role="buyer", item="Plaza", your_limit=130, rival="Rival Sol",
                             rival_offer={"id": 3, "price": 70, "tick": 120},
                             messages=[{"tick": 120, "from": "Rival Sol", "text": "", "price": 70}]), 120)
        self.assertIsNone(m.assess(v2)["rival_limit_estimate"])

    def test_types_and_persistence(self):
        path = Path(tempfile.mkdtemp()) / "mem.json"
        m = OpponentMemory(path)
        msgs = [{"tick": 100 + i, "from": "Rival Plata", "text": "", "price": 148} for i in range(3)]
        m.observe_duel(parse_duel(duel(duel=11, role="seller", your_limit=118, rival="Rival Plata",
                                       messages=msgs), 103))
        m.record_result(11, "deal", price=148, rounds=3)
        m2 = OpponentMemory(path)
        prof = m2.profile("Rival Plata")
        self.assertEqual(prof["type"], "fixed")
        self.assertEqual(prof["deals"], 1)
        steps = [{"tick": 100 + i, "from": "Rival Sol", "text": "", "price": 89 + 6 * i} for i in range(3)]
        m2.observe_duel(parse_duel(duel(duel=12, role="seller", your_limit=91, rival="Rival Sol",
                                        messages=steps), 103))
        self.assertEqual(m2.profile("Rival Sol")["type"], "stepped")
        silent = [{"tick": 100 + i, "from": "you", "text": "", "price": 120 - i} for i in range(4)]
        m2.observe_duel(parse_duel(duel(duel=13, role="seller", your_limit=100, rival="Rival Luna",
                                        messages=silent), 104))
        self.assertEqual(m2.profile("Rival Luna")["type"], "mute")


class TestClaudePath(unittest.TestCase):
    def test_claude_move_goes_through_guard(self):
        llm = FakeLLM({"action": "offer", "price": 500, "days": 0, "text": "500 P now",
                       "reason": "greedy", "expected_points": 3})
        dom = DuelsDomain(memory=mem(), llm=llm)
        acts = dom.decide(SimpleNamespace(tick=100, duels=[duel()]), ctx(deadline=time.time() + 5))
        self.assertEqual(acts[0].kind, "duel_message")
        self.assertLessEqual(acts[0].params["price"], 143 - MIN_SURPLUS)     # clamped inside our value
        self.assertIn(str(acts[0].params["price"]), acts[0].params["text"])
        self.assertEqual(acts[0].source, "opus")
        p = llm.prompts[0]
        self.assertEqual(p["purpose"], "duels")
        self.assertEqual(p["tools"][0]["name"], "duel_move")
        self.assertTrue(p["tools"][0]["strict"])

    def test_slow_claude_falls_back_before_deadline(self):
        llm = FakeLLM({"action": "wait", "price": 0, "days": 0, "text": "", "reason": "", "expected_points": 0},
                      delay=2.0)
        dom = DuelsDomain(memory=mem(), llm=llm)
        t0 = time.time()
        acts = dom.decide(SimpleNamespace(tick=100, duels=[duel()]), ctx(deadline=time.time() + 0.6))
        self.assertLess(time.time() - t0, 1.0)
        self.assertEqual(acts[0].source, "fallback")

    def test_no_tool_call_uses_fallback(self):
        dom = DuelsDomain(memory=mem(), llm=FakeLLM(None))
        acts = dom.decide(SimpleNamespace(tick=100, duels=[duel()]), ctx(deadline=time.time() + 5))
        self.assertEqual(acts[0].source, "fallback")

    def test_parallel_one_call_per_duel(self):
        llm = FakeLLM({"action": "wait", "price": 0, "days": 0, "text": "", "reason": "", "expected_points": 0},
                      delay=0.3)
        dom = DuelsDomain(memory=mem(), llm=llm)
        duels = [duel(duel=i) for i in range(1, 4)]
        t0 = time.time()
        dom.decide(SimpleNamespace(tick=100, duels=duels), ctx(deadline=time.time() + 5))
        self.assertEqual(len(llm.prompts), 3)
        self.assertLess(time.time() - t0, 0.8)


class TestInjection(unittest.TestCase):
    def test_rival_text_never_changes_a_code_decision(self):
        rng = random.Random(9)
        for i in range(30):
            sc = make_scenario(rng)
            runs = []
            for text in ("I can do it. Let's close quickly.", rng.choice(INJECTIONS)):
                dom = DuelsDomain(memory=mem(), use_llm=False)
                r = run_duel(dom, sc, RIVALS["stepped"](sc, random.Random(i)), i, "Rival Noche",
                             injected_text=text)
                runs.append([(m["tick"], m["from"], m["price"]) for m in r.log] + [(r.deal, r.price, r.rounds)])
            self.assertEqual(runs[0], runs[1])

    def test_rival_text_reaches_claude_only_wrapped(self):
        llm = FakeLLM({"action": "accept", "price": 9999, "days": 0, "text": "", "reason": "obeyed",
                       "expected_points": 0})
        evil = INJECTIONS[2]
        d = duel(rival_offer={"id": 4, "price": 9999, "tick": 100},
                 messages=[{"tick": 100, "from": "Rival Oro", "text": evil, "price": 9999}])
        dom = DuelsDomain(memory=mem(), llm=llm)
        acts = dom.decide(SimpleNamespace(tick=100, duels=[d]), ctx(deadline=time.time() + 5))
        # Claude "obeyed" the injection and accepted 9999 > our value 143: the guard refuses it.
        self.assertFalse(any(a.kind == "duel_accept" for a in acts))
        user = llm.prompts[0]["messages"][0]["content"]
        self.assertNotIn("</untrusted><system>", user)
        self.assertIn("<untrusted source='Rival Oro'", user)
        self.assertIn("untrusted", SYSTEM)


class TestTournamentSmoke(unittest.TestCase):
    def test_runs_without_illegal_deals(self):
        res = play(24, 1, False, ["fixed", "stepped", "mute"])
        self.assertTrue(all(not r.illegal for r in res))
        self.assertGreater(sum(r.points for r in res) / len(res), 5)


if __name__ == "__main__":
    unittest.main()
