"""Round-2 audit fixes: fallback message on a lost accept, whole-duel rounds, short ticks, Claude's weight,
second-leg alias, ambiguous days, tough rivals."""
from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from bazaar import config
from bazaar.core.arbiter import select
from bazaar.duels.domain import DuelsDomain, accept_priority, urgent_ticks
from bazaar.duels.model import MIN_SURPLUS, parse_duel
from bazaar.duels.policy import Move, bound_claude, choose_days, economics, plan
from bazaar.duels.prompt import SYSTEM
from bazaar.duels.tests.test_duels import FakeLLM, ctx, duel, mem
from bazaar.llm.client import LLMTimeout


def msgs(seq, start=100):
    """seq of ("us"|"r", price): one message per tick."""
    return [{"tick": start + i, "from": "you" if who == "us" else "Rival Oro", "text": "", "price": p}
            for i, (who, p) in enumerate(seq)]


class TestFallbackMessage(unittest.TestCase):
    def test_accept_carries_rival_terms_and_arbiter_substitutes(self):
        dom = DuelsDomain(memory=mem(), use_llm=False)
        # two duels, each with a rival offer we take (buyer, value 143: 60 is a gift)
        d1 = duel(duel=1, rival_offer={"id": 1, "price": 60, "tick": 100},
                  messages=msgs([("r", 60)]), deadline_tick=102)
        d2 = duel(duel=2, rival_offer={"id": 2, "price": 61, "tick": 100},
                  messages=msgs([("r", 61)]), deadline_tick=110)
        acts = dom.fallback(SimpleNamespace(tick=100, duels=[d1, d2]), ctx())
        self.assertEqual([a.kind for a in acts], ["duel_accept", "duel_accept"])
        for a in acts:
            fm = a.params["fallback_message"]
            self.assertEqual(fm["price"], a.params["expect"]["price"])
            self.assertIn(str(fm["price"]), fm["text"])
        chosen, _ = select(acts, SimpleNamespace(tick=100, limits={}, threads=[], my_offers=[], duels=[]),
                           {"accepts_left": 1, "duel_accepts_left": 1, "messages": {}})
        self.assertEqual([(c.kind, c.params["duel"]) for c in chosen], [("duel_accept", 1), ("duel_message", 2)])
        self.assertEqual(chosen[1].params["price"], 61)

    def test_days_in_fallback_message(self):
        dom = DuelsDomain(memory=mem(), use_llm=False)
        d = duel(issues=["price", "days"], your_days_weight=1.0, days_meaning="value to you per day",
                 decay_per_round=0.08, rival_offer={"id": 1, "price": 50, "days": 7, "tick": 100},
                 messages=[{"tick": 100, "from": "Rival Oro", "text": "", "price": 50, "days": 7}])
        a = dom.fallback(SimpleNamespace(tick=100, duels=[d]), ctx())[0]
        self.assertEqual(a.kind, "duel_accept")
        self.assertEqual((a.params["fallback_message"]["price"], a.params["fallback_message"]["days"]), (50, 7))

    def test_urgent_threshold_scales_with_accepts_waiting(self):
        self.assertEqual(urgent_ticks(1), 2)
        self.assertEqual(urgent_ticks(5), 5)
        self.assertLess(accept_priority(10, 4, 1), 150)
        self.assertGreaterEqual(accept_priority(10, 4, 5), 150)
        # closer deadline wins among urgent ones at equal points
        self.assertGreater(accept_priority(10, 1, 3), accept_priority(10, 3, 3))
        self.assertLess(accept_priority(500, 1, 9), 200)

    def test_last_ticks_scale_with_queue(self):
        v = parse_duel(duel(rival_offer={"id": 1, "price": 135, "tick": 100},
                            messages=msgs([("us", 80), ("r", 140), ("us", 85), ("r", 135)], start=97),
                            deadline_tick=104), 100)      # 4 ticks left, margin 8 of a ~50 pie
        opp = mem().assess(v)
        self.assertNotEqual(plan(v, dict(opp, accept_queue=1)).action, "accept")
        self.assertEqual(plan(v, dict(opp, accept_queue=5)).action, "accept")


class TestWholeDuelRounds(unittest.TestCase):
    def test_rounds_from_memory_not_window(self):
        m = mem()
        seq = [("us", 80), ("r", 140), ("us", 82), ("r", 138), ("r", 136), ("us", 84), ("r", 134), ("r", 133)]
        full = msgs(seq)
        for k in range(1, len(seq) + 1):        # the bot sees the duel tick by tick, 6 messages at most
            win = full[:k][-6:]
            v = parse_duel(duel(rounds=min(sum(1 for w, _ in seq[:k] if w == "us"),
                                           sum(1 for w, _ in seq[:k] if w == "r")),
                                messages=win), 100 + k - 1)
            m.assess(v)
        # whole duel: 3 ours, 5 theirs -> rounds 3; we owe answers, a counter costs a round
        self.assertEqual(v.offer_counts(), (3, 5))
        self.assertEqual(v.rounds_if_we_send(), 4)
        econ = economics(v, m.assess(v), (90, None))
        self.assertEqual(econ["rounds_if_we_send"], 4)
        # the window alone would have said 2 ours / 4 theirs; with server rounds as floor it never undercounts
        w = parse_duel(duel(rounds=3, messages=full[-6:]), 107)
        self.assertGreaterEqual(min(w.offer_counts()), 3)


class RaceLLM(FakeLLM):
    def __init__(self, move, fail_first=False):
        super().__init__(move)
        self.raced, self.asked_models, self.fail_first = [], [], fail_first

    def ask(self, **kw):
        self.asked_models.append(kw.get("model"))
        return super().ask(**kw)

    def race(self, *, models, **kw):
        self.raced.append(models)
        if self.fail_first and len(self.raced) == 1:
            raise LLMTimeout("slow")
        return super().ask(**kw)


class TestShortTicks(unittest.TestCase):
    MOVE = {"action": "offer", "price": 95, "days": 0, "text": "95 P works.", "reason": "r",
            "expected_points": 1, "lesson_ids": []}

    def test_race_on_short_ticks_and_retry_after_timeout(self):
        llm = RaceLLM(self.MOVE, fail_first=True)
        dom = DuelsDomain(memory=mem(), llm=llm)
        c = ctx(tick_seconds=15, deadline=time.time() + 8)
        dom.decide(SimpleNamespace(tick=100, duels=[duel()]), c)
        self.assertEqual(llm.raced, [[config.OPUS, config.SONNET]])
        self.assertNotIn(7, dom._last_ask)                    # failed call: not stamped
        dom.decide(SimpleNamespace(tick=101, duels=[duel()]), ctx(tick_seconds=15, deadline=time.time() + 8))
        self.assertEqual(len(llm.raced), 2)                   # retried next tick
        self.assertIn(7, dom._last_ask)

    def test_sonnet_alone_when_little_time(self):
        llm = RaceLLM(self.MOVE)
        dom = DuelsDomain(memory=mem(), llm=llm)
        dom.decide(SimpleNamespace(tick=100, duels=[duel()]), ctx(tick_seconds=15, deadline=time.time() + 3))
        self.assertEqual(llm.raced, [])
        self.assertEqual(llm.asked_models, [config.SONNET])

    def test_normal_ticks_plain_ask(self):
        llm = RaceLLM(self.MOVE)
        DuelsDomain(memory=mem(), llm=llm).decide(SimpleNamespace(tick=100, duels=[duel()]),
                                                   ctx(tick_seconds=30, deadline=time.time() + 15))
        self.assertEqual(llm.raced, [])


class TestClaudeWeight(unittest.TestCase):
    def stepped_view(self):
        m = mem()
        # a known stepper (history with this alias) so the archetype is not unknown
        for i, did in enumerate((1, 2)):
            m.observe_duel(parse_duel(duel(duel=did, item=f"X{i}", messages=msgs(
                [("r", 140), ("us", 80), ("r", 135), ("us", 82), ("r", 130)])), 105))
        v = parse_duel(duel(rival_offer={"id": 1, "price": 130, "tick": 102},
                            messages=msgs([("r", 140), ("us", 80), ("r", 135), ("us", 82), ("r", 130)], start=98)),
                       103)
        opp = m.assess(v)
        return v, opp

    def test_bounded_raises_a_cheap_ask(self):
        v, opp = self.stepped_view()
        self.assertNotEqual(opp["type"], "unknown")
        base = Move("offer", 84, None)
        mv, notes = bound_claude(v, Move("offer", 120, None, text="120 P"), base, opp, {}, "bounded")
        tol = max(2, 0.1 * opp["pie_estimate"])
        self.assertTrue(notes)
        self.assertGreaterEqual(v.utility(mv.price, None), v.utility(84, None) - tol - 1e-9)
        # within tolerance: Claude's price stands
        mv2, notes2 = bound_claude(v, Move("offer", 85, None, text="85 P"), base, opp, {}, "bounded")
        self.assertEqual((mv2.price, notes2), (85, []))
        # full mode: untouched
        mv3, _ = bound_claude(v, Move("offer", 120, None), base, opp, {}, "full")
        self.assertEqual(mv3.price, 120)

    def test_bounded_accept_and_wait_need_economics(self):
        v, opp = self.stepped_view()
        econ = {"accept_now": {"points": 10.0}, "their_next_offer_if_we_counter": {"points_est": 14.0}}
        base = Move("offer", 84, None)
        mv, _ = bound_claude(v, Move("accept"), base, opp, econ, "bounded")
        self.assertIs(mv, base)
        econ_ok = {"accept_now": {"points": 13.5}, "their_next_offer_if_we_counter": {"points_est": 14.0}}
        self.assertEqual(bound_claude(v, Move("accept"), base, opp, econ_ok, "bounded")[0].action, "accept")
        acc = Move("accept", 130, None)
        self.assertIs(bound_claude(v, Move("wait"), acc, opp, econ, "bounded")[0].action, "wait")
        econ_acc = {"accept_now": {"points": 16.0}, "their_next_offer_if_we_counter": {"points_est": 14.0}}
        self.assertIs(bound_claude(v, Move("wait"), acc, opp, econ_acc, "bounded")[0], acc)

    def test_full_weight_on_days_and_unknown(self):
        v = parse_duel(duel(), 100)
        opp = mem().assess(v)
        self.assertEqual(opp["type"], "unknown")
        self.assertEqual(bound_claude(v, Move("offer", 140, None), Move("offer", 80, None), opp, {})[0].price, 140)

    def test_code_mode_never_calls_claude(self):
        llm = FakeLLM({"action": "wait", "price": 0, "days": 0, "text": "", "reason": "", "expected_points": 0,
                       "lesson_ids": []})
        dom = DuelsDomain(memory=mem(), llm=llm)
        acts = dom.decide(SimpleNamespace(tick=100, duels=[duel()]), ctx(control={"duel_claude_mode": "code"}))
        self.assertEqual(llm.prompts, [])
        self.assertEqual(acts[0].source, "fallback")

    def test_prompt_teaches_the_new_rules(self):
        for s in ("FRESH rival offer", "Big concessions cost margin", "free_steps_here > 0", "midpoint"):
            self.assertIn(s, SYSTEM)


class TestSecondLegAlias(unittest.TestCase):
    def test_other_alias_is_capped(self):
        m = mem()
        m.observe_duel(parse_duel(duel(duel=1, role="seller", item="Plaza", your_limit=20, rival="Rival Luz"), 100))
        # leg against another alias: limit 20 would mean pie 110 for us; offers say ~10-20
        v = parse_duel(duel(duel=2, role="buyer", item="Plaza", your_limit=130, rival="Rival Sol",
                            rival_offer={"id": 3, "price": 125, "tick": 120},
                            messages=[{"tick": 120, "from": "Rival Sol", "text": "", "price": 125}]), 120)
        a = m.assess(v)
        self.assertIsNone(a["rival_limit_estimate"])
        m2 = mem()
        m2.observe_duel(parse_duel(duel(duel=1, role="seller", item="Plaza", your_limit=20, rival="Rival Luz"), 100))
        m2.data["items"]["Plaza"]["seller"].clear()
        uncapped = m2.assess(v)["pie_estimate"]
        self.assertLessEqual(a["pie_estimate"], 1.5 * uncapped + 1e-6)
        self.assertLess(a["pie_estimate"], 110)
        # same alias: trusted
        m3 = mem()
        m3.observe_duel(parse_duel(duel(duel=1, role="seller", item="Plaza", your_limit=20, rival="Rival Sol"), 100))
        self.assertEqual(m3.assess(v)["rival_limit_estimate"], 20)


class TestAmbiguousDays(unittest.TestCase):
    def view(self, w, rival_days, **kw):
        return parse_duel(duel(issues=["price", "days"], your_days_weight=w, days_meaning="days",
                               decay_per_round=0.08, rival_offer={"id": 1, "price": 120, "days": rival_days,
                                                                   "tick": 100},
                               messages=[{"tick": 100, "from": "Rival Oro", "text": "", "price": 120,
                                          "days": rival_days}], **kw), 100)

    def test_rival_days_only_if_padding_small(self):
        v = self.view(0.5, 8)                  # padding 4 P
        self.assertTrue(v.days_ambiguous)
        self.assertEqual(choose_days(v, pie=40), 8)       # 4 < 10
        self.assertEqual(choose_days(v, pie=10), 0)       # 4 >= 2.5
        self.assertEqual(choose_days(self.view(3.0, 8), pie=40), 0)   # 24 >= 10

    def test_operator_override(self):
        dom = DuelsDomain(memory=mem(), use_llm=False)
        d = duel(issues=["price", "days"], your_days_weight=2.0, days_meaning="days", decay_per_round=0.08)
        sit = SimpleNamespace(tick=100, duels=[d])
        views = dom._views(sit, ctx(control={"duel_days_sign": "cost"}))
        self.assertEqual((views[0].days_w, views[0].days_ambiguous), (-2.0, False))
        views = dom._views(sit, ctx(control={"duel_days_sign": "value"}))
        self.assertEqual((views[0].days_w, views[0].days_ambiguous), (2.0, False))
        self.assertTrue(dom._views(sit, ctx(control={}))[0].days_ambiguous)
        a = dom.fallback(sit, ctx(control={"duel_days_sign": "cost"}))[0]
        self.assertEqual(a.params["days"], 0)


class TestToughRival(unittest.TestCase):
    def test_jump_to_midpoint_or_take(self):
        # buyer, value 143; rival moves 1 P per offer after 3 offers, offers inside our limit
        seq = [("us", 90), ("r", 133), ("us", 92), ("r", 132), ("us", 94), ("r", 131)]
        m = mem()
        v = parse_duel(duel(rival_offer={"id": 1, "price": 131, "tick": 105}, messages=msgs(seq),
                            deadline_tick=120, rounds=3), 105)
        opp = m.assess(v)
        self.assertTrue(opp["tough_now"])
        mv = plan(v, opp)
        # our ask 49, theirs 12: midpoint 30.5 -> offer ~112 (not another 1-2 P step)
        self.assertEqual(mv.action, "offer")
        self.assertLessEqual(abs(v.utility(mv.price, None) - 30.5), 1)
        # close to us: take it
        seq2 = [("us", 120), ("r", 128), ("us", 121), ("r", 127), ("us", 122), ("r", 126)]
        v2 = parse_duel(duel(rival_offer={"id": 1, "price": 126, "tick": 105}, messages=msgs(seq2),
                             deadline_tick=120, rounds=3), 105)
        self.assertEqual(plan(v2, mem().assess(v2)).action, "accept")


if __name__ == "__main__":
    unittest.main()
