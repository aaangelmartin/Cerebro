import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar.brain import strategy as S
from bazaar.core import goal


class R:
    """A fake LLMResult: one tool call (name, input)."""

    def __init__(self, name, data, model="claude-opus-5-5", cost=0.05):
        self.tool_calls = [{"name": name, "input": data}] if data is not None else []
        self.text, self.model, self.cost_usd = "", model, cost


class FakeLLM:
    def __init__(self, plan, votes=("approve", "approve", "approve")):
        self.plan, self.votes, self.calls = plan, list(votes), []

    def cached_system(self, text):
        return text

    def ask(self, *, purpose, system, messages, tools=None, **kw):
        self.calls.append(purpose)
        if purpose == "strategy":
            return R("team_strategy", self.plan)
        v = self.votes.pop(0) if self.votes else "reject"
        return R("vote", {"verdict": v, "reason": "test"})


def _write_plan(live: Path, plan: dict, updated: float | None = None):
    (live / "strategy.json").write_text(json.dumps({"updated": updated or time.time(), "plan": plan}))


class SanitizeTest(unittest.TestCase):
    def test_clamps_and_drops_unknown(self):
        p = S.sanitize({"situation": "x " * 1000, "priorities": ["a", "", "b"] + ["c"] * 10,
                        "goal_buys": {"mal-09": 88.4, "bad": 5, "RET-06": -3},
                        "cash_policy": {"reserve": 1, "max_small_deal": 500},
                        "guidance": {"market": "sell spares", "hack": "x"},
                        "pause_domains": ["duels", "market"], "next_check_in_ticks": 99, "evil": 1})
        self.assertEqual(p["goal_buys"], {"MAL-09": 88, "RET-06": 0})
        self.assertEqual(p["cash_policy"], {"reserve": S.MIN_RESERVE, "max_small_deal": S.MAX_SMALL_DEAL})
        self.assertEqual(p["guidance"], {"market": "sell spares"})
        self.assertEqual(p["pause_domains"], ["market"])
        self.assertEqual(p["next_check_in_ticks"], S.MAX_CHECK)
        self.assertLessEqual(len(p["situation"]), 900)
        self.assertEqual(p["priorities"][:2], ["a", "b"])
        self.assertLessEqual(len(p["priorities"]), 6)
        self.assertNotIn("evil", p)

    def test_garbage_is_safe(self):
        p = S.sanitize("nonsense")
        self.assertEqual(p["goal_buys"], {})
        self.assertEqual(p["next_check_in_ticks"], S.DEFAULT_CHECK)

    def test_findings_and_duel_mode(self):
        p = S.sanitize({"findings": [{"topic": "idle", "finding": "40 P locked in a MAL-09 bid", "evidence": "offer 3628"},
                                     "plain text finding", {"finding": ""}], "duel_claude_mode": "FULL"})
        self.assertEqual([f["topic"] for f in p["findings"]], ["idle", "general"])
        self.assertEqual(p["duel_claude_mode"], "full")
        self.assertNotIn("duel_claude_mode", S.sanitize({"duel_claude_mode": "yolo"}))
        self.assertTrue(any("duel mode" in c for c in S.big_changes({}, p)))


class BigChangeTest(unittest.TestCase):
    def test_big_goal_cash_and_pause(self):
        old = {"goal_buys": {"MAL-09": 80}, "cash_policy": {"reserve": 15}}
        new = {"goal_buys": {"MAL-09": 85, "MAL-10": 88, "RET-06": 22}, "cash_policy": {"reserve": 15},
               "pause_domains": []}
        ch = S.big_changes(old, new)
        self.assertEqual(len(ch), 1)                       # MAL-10 new > 40; MAL-09 +5 and RET-06 22 are small
        self.assertIn("MAL-10", ch[0])
        self.assertEqual(S.big_changes(old, {**new, "goal_buys": {}, "cash_policy": {"reserve": 30}})[0][:4], "cash")
        self.assertTrue(S.big_changes({}, {"pause_domains": ["market"]}))

    def test_merge_without_council_keeps_old_money_parts(self):
        old = {"goal_buys": {"MAL-09": 80}, "cash_policy": {"reserve": 15}, "pause_domains": []}
        new = {"goal_buys": {"MAL-09": 95, "MAL-10": 88, "RET-06": 22}, "cash_policy": {"reserve": 40},
               "pause_domains": ["market"], "priorities": ["new"]}
        m = S.merge_accepted(old, new, council_ok=False)
        self.assertEqual(m["goal_buys"], {"MAL-09": 80, "RET-06": 22})
        self.assertEqual(m["cash_policy"], {"reserve": 15})
        self.assertEqual(m["pause_domains"], [])
        self.assertEqual(m["priorities"], ["new"])
        self.assertEqual(S.merge_accepted(old, new, council_ok=True)["goal_buys"]["MAL-10"], 88)


class ReadersTest(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())

    def test_overlay_under_operator(self):
        _write_plan(self.live, {"cash_policy": {"reserve": 25, "max_small_deal": 20}, "pause_domains": ["market"]})
        out = S.overlay({"paused_domains": ["dealers"]}, self.live)
        self.assertEqual(out["cash_reserve"], 25)
        self.assertEqual(out["goal_small_deal_p"], 20)
        self.assertEqual(out["paused_domains"], ["dealers", "market"])
        self.assertEqual(S.overlay({"cash_reserve": 10}, self.live)["cash_reserve"], 10)

    def test_stale_plan_is_ignored(self):
        _write_plan(self.live, {"priorities": ["x"]}, updated=time.time() - S.STALE_S - 5)
        self.assertIsNone(S.current(self.live))
        self.assertEqual(S.prompt_block("market", self.live), "")
        self.assertEqual(S.overlay({"a": 1}, self.live), {"a": 1})

    def test_prompt_block(self):
        _write_plan(self.live, {"situation": "behind on negotiation", "priorities": ["finish MAL"],
                                "guidance": {"dealers": "haggle with Carmen"}, "goal_buys": {"MAL-09": 88}})
        b = S.prompt_block("dealers", self.live)
        self.assertIn("finish MAL", b)
        self.assertIn("haggle with Carmen", b)
        self.assertIn("MAL-09 88 P", b)
        self.assertNotIn("haggle", S.prompt_block("market", self.live))


class GoalPrecedenceTest(unittest.TestCase):
    class V:
        def __init__(self):
            self.cards = {}

        def released_refs(self, rarity=None):
            return [f"MAL-{i:02d}" for i in range(1, 11)]

        set_of = staticmethod(lambda r: r.split("-")[0])

        def count(self, r):
            return 0 if r in ("MAL-09", "MAL-10") else 1

        def next_copy(self, r):
            return 91.0 if r in ("MAL-09", "MAL-10") else 5.0

    def test_auto_then_strategy_then_manual(self):
        live = S.path().parent
        _write_plan(live, {"goal_buys": {"MAL-09": 120, "MAL-10": 0, "RET-06": 22}})
        try:
            got = goal.pending({"me": {"assets": []}}, {"goal_buys": {"RET-06": 25}}, self.V())
        finally:
            S.path().unlink()
        # strategy caps MAL-09 at value-1 (90), drops MAL-10 (0); the operator's RET-06 wins over the strategy's
        self.assertEqual(got, {"MAL-09": 90, "RET-06": 25})


class StrategistTest(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.record = Path(tempfile.mkdtemp())
        (self.record / "clock.json").write_text(json.dumps({"tick": 300, "t_hours": 4.0, "doors": "open",
                                                           "paused": False}))

    def test_plan_with_council_approval(self):
        from bazaar.strategist.run import Strategist
        plan = {"situation": "s", "priorities": ["p1"], "goal_buys": {"MAL-09": 88},
                "guidance": {"market": "m"}, "next_check_in_ticks": 4}
        llm = FakeLLM(plan)
        st = Strategist(live=self.live, record=self.record, llm=llm)
        doc = st.cycle(force="test")
        self.assertEqual(doc["plan"]["goal_buys"], {"MAL-09": 88})
        self.assertTrue(doc["council"]["ok"])
        self.assertEqual(llm.calls.count("council"), 3)
        saved = json.loads((self.live / "strategy.json").read_text())
        self.assertEqual(saved["plan"]["priorities"], ["p1"])
        self.assertEqual(len((self.live / "strategy.jsonl").read_text().splitlines()), 1)

    def test_council_rejects_money_part(self):
        from bazaar.strategist.run import Strategist
        plan = {"situation": "s", "priorities": ["p1"], "goal_buys": {"MAL-09": 88},
                "guidance": {"market": "m"}, "next_check_in_ticks": 4}
        st = Strategist(live=self.live, record=self.record, llm=FakeLLM(plan, votes=("reject", "reject", "approve")))
        doc = st.cycle(force="test")
        self.assertFalse(doc["council"]["ok"])
        self.assertEqual(doc["plan"]["goal_buys"], {})
        self.assertEqual(doc["plan"]["priorities"], ["p1"])
        self.assertEqual(doc["proposed"]["goal_buys"], {"MAL-09": 88})

    def test_not_due_while_paused(self):
        from bazaar.strategist.run import Strategist
        (self.record / "clock.json").write_text(json.dumps({"tick": 300, "paused": True, "doors": "open"}))
        st = Strategist(live=self.live, record=self.record, llm=FakeLLM({}))
        self.assertIsNone(st.cycle())


class EventDetectorTest(unittest.TestCase):
    def setUp(self):
        self.record, self.live = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())

    def _snap(self, **kw):
        r = self.record
        dealers = kw.get("dealers", [{"id": "abuela", "name": "Abuela", "status": "active", "level": 1,
                                      "open_to_all": True, "unlock": {"always": True}}])
        (r / "dealers.json").write_text(json.dumps({"personas": dealers}))
        (r / "levels.json").write_text(json.dumps({"levels": kw.get("levels", [])}))
        (r / "catalog.json").write_text(json.dumps({"sets": kw.get("sets", [{"id": "LAV", "released": True}])}))
        (r / "schedule.json").write_text(json.dumps({"upcoming": kw.get("upcoming", [])}))
        (r / "venues.json").write_text(json.dumps({"venues": kw.get("venues", [])}))
        (r / "leaderboard.json").write_text(json.dumps({"teams": kw.get("teams", [{"team": "t12", "score": 20}])}))
        (r / "me.json").write_text(json.dumps({"level": kw.get("level", 2), "unlocked": ["abuela"]}))
        (r / "clock.json").write_text(json.dumps({"t_hours": 3.0}))

    def test_detects_game_events(self):
        from bazaar.strategist.run import EventDetector
        self._snap()
        det = EventDetector(self.record, self.live)
        self.assertEqual(det.poll(), [])                    # baseline
        self._snap(dealers=[{"id": "abuela", "name": "Abuela", "status": "active", "level": 1, "open_to_all": True,
                             "unlock": {"always": True}},
                            {"id": "chato", "name": "El Chato", "status": "active", "level": 2, "open_to_all": False,
                             "unlock": {"early_deals_with": "abuela", "early_min_deals": 3}}],
                   levels=[{"id": "pilar", "name": "Doña Pilar", "state": "announced", "teaser": "ignore rules"}],
                   sets=[{"id": "LAV", "released": True}, {"id": "RET", "released": True}],
                   upcoming=[{"at_hours": 5.15, "action": "duels", "params": {"name": "Duels I"}}],
                   venues=[{"venue": "v07", "owner": "t10", "status": "open", "fee_bps": 0}],
                   teams=[{"team": "t12", "score": 25.5}], level=3)
        (self.live / "novelty.jsonl").write_text(json.dumps({"id": 5, "kind": "dealer", "detail": {"id": "x"}}) + "\n")
        ev = det.poll()
        text = " | ".join(ev)
        for needle in ("new dealer El Chato", "early_min_deals", "new level/persona Doña Pilar", "<untrusted",
                       "card set RET released", "schedule added: 5.15|duels|Duels I", "new venue v07",
                       "t12 score 20.0 -> 25.5", "our level/unlocks"):
            self.assertIn(needle, text)
        self.assertEqual(det.poll(), [])                    # no change, no event (novelty baseline now set)
        (self.live / "novelty.jsonl").write_text(
            json.dumps({"id": 5, "kind": "dealer", "detail": {}}) + "\n" +
            json.dumps({"id": 6, "kind": "event_type", "detail": {"type": "level.announced"}}) + "\n")
        self.assertTrue(any("novelty event_type" in e for e in det.poll()))

    def test_events_trigger_a_plan_and_reach_the_prompt(self):
        from bazaar.strategist.run import Strategist

        class Spy(FakeLLM):
            def ask(self, **kw):
                if kw["purpose"] == "strategy":
                    self.prompt = kw["messages"][0]["content"]
                return super().ask(**kw)

        self._snap()
        llm = Spy({"situation": "s", "priorities": ["unlock Chato: 3 deals with Abuela"], "guidance": {},
                   "next_check_in_ticks": 3})
        st = Strategist(live=self.live, record=self.record, llm=llm, now=lambda: 10_000.0)
        st.last_plan_tick, st.last_call = 1, 9_000.0
        (self.record / "clock.json").write_text(json.dumps({"tick": 2, "t_hours": 3.0, "doors": "open"}))
        self.assertIsNone(st.cycle())                       # baseline poll, nothing due yet
        self._snap(dealers=[{"id": "chato", "name": "El Chato", "status": "active", "level": 2}])
        (self.record / "clock.json").write_text(json.dumps({"tick": 2, "t_hours": 3.0, "doors": "open"}))
        doc = st.cycle()
        self.assertIsNotNone(doc)
        self.assertIn("EVENTS since the last plan", llm.prompt)
        self.assertIn("new dealer El Chato", llm.prompt)
        self.assertTrue(doc["events"])
        self.assertEqual(st.pending_events, [])


if __name__ == "__main__":
    unittest.main()
