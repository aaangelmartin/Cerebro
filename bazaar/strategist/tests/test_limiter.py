import json
import tempfile
import unittest
from pathlib import Path

from bazaar.strategist import limiter as L


class Act:
    def __init__(self, kind="post_offer", params=None, expected=None):
        self.kind, self.params, self.expected = kind, params or {}, expected or {}


def llm_rows(path: Path, rows):
    with open(path / "llm.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class GapTest(unittest.TestCase):
    def test_gap_table(self):
        self.assertEqual(L.min_gap_s(40), 240)
        self.assertGreater(L.min_gap_s(0), L.min_gap_s(50))
        self.assertGreaterEqual(L.min_gap_s(100), 60)

    def test_events_never_cut_the_gap(self):
        g = L.gate(now=1000, level=40, last_plan_ts=900, has_chat=False)
        self.assertFalse(g["ok"])
        self.assertTrue(L.gate(now=1000, level=40, last_plan_ts=700, has_chat=False)["ok"])

    def test_chat_cuts_the_gap_but_is_coalesced(self):
        self.assertTrue(L.gate(now=1000, level=40, last_plan_ts=950, has_chat=True, last_chat_plan_ts=800)["ok"])
        g = L.gate(now=1000, level=40, last_plan_ts=950, has_chat=True, last_chat_plan_ts=950)
        self.assertFalse(g["ok"])                       # a second chat plan must wait 120 s: messages are answered together
        self.assertTrue(L.gate(now=1075, level=40, last_plan_ts=950, has_chat=True, last_chat_plan_ts=950)["ok"])

    def test_emergency_once_per_ten_minutes(self):
        ev = [{"kind": "bargain", "data": {"gain": 150, "gap": 28}}]
        self.assertTrue(L.is_emergency(ev))
        self.assertFalse(L.is_emergency([{"kind": "bargain", "data": {"gain": 150, "gap": 0}}]))
        self.assertFalse(L.is_emergency([{"kind": "bargain", "data": {"gain": 10, "gap": 5}}]))
        self.assertTrue(L.gate(now=1000, level=40, last_plan_ts=930, has_chat=False, emergency=True)["ok"])
        self.assertFalse(L.gate(now=1000, level=40, last_plan_ts=970, has_chat=False, emergency=True)["ok"])
        self.assertFalse(L.gate(now=1000, level=40, last_plan_ts=930, has_chat=False, emergency=True,
                                last_emergency_ts=700)["ok"])

    def test_empty_bucket_skips_the_plan(self):
        b = {"ok": False, "spent": 3.0, "allowed": 2.5}
        g = L.gate(now=5000, level=40, last_plan_ts=0, has_chat=False, strategy_bucket=b)
        self.assertFalse(g["ok"])
        self.assertIn("keeping the last plan", g["why"])
        self.assertTrue(L.gate(now=5000, level=40, last_plan_ts=0, has_chat=True, strategy_bucket=b)["ok"])
        self.assertFalse(L.gate(now=5000, level=40, last_plan_ts=4800, has_chat=True, strategy_bucket=b,
                                chat_bucket_ok=False)["ok"])              # far above the pace: one chat plan per 300 s
        self.assertTrue(L.gate(now=5000, level=40, last_plan_ts=4600, has_chat=True, last_chat_plan_ts=4600,
                               strategy_bucket=b, chat_bucket_ok=False)["ok"])


class BucketTest(unittest.TestCase):
    def test_rolling_spend_and_targets(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            llm_rows(live, [{"ts": 100, "purpose": "strategy", "cost_usd": 9.0},          # too old
                            {"ts": 9000, "purpose": "strategy", "cost_usd": 1.0},
                            {"ts": 9500, "purpose": "strategy", "cost_usd": 1.5},
                            {"ts": 9600, "purpose": "council", "cost_usd": 0.5},
                            {"ts": 9700, "purpose": "duels", "cost_usd": 3.0}])
            self.assertEqual(L.spent_window(live, ("strategy",), now=10000), 2.5)
            self.assertTrue(L.bucket("strategy", 4.8, live, now=10000)["ok"])              # 4.8 x 1.25 / 2 = 3.0
            self.assertFalse(L.bucket("strategy", 3.0, live, now=10000)["ok"])             # 1.875 allowed
            t = L.trailing(live, now=10000)
            self.assertEqual((t["all"], t["brain"], t["council"]), (12.0, 5.0, 1.0))
        tg = L.targets({"purpose_caps": {"strategy": 85, "council": 27.7},
                        "spent_by_purpose": {"strategy": 48, "council": 14.2}, "brain_left_today": 37}, 6.7, 4.73)
        self.assertEqual(tg["strategy"], 4.73)                                             # the manual level's own cost
        self.assertAlmostEqual(tg["council"], 2.01, places=2)
        self.assertEqual(L.targets({}, 5.0)["council"], 2.0)


class CouncilTest(unittest.TestCase):
    def test_material_errors(self):
        self.assertFalse(L.material(["priority 2 cites no number (values, prices or scores): 'x'"]))
        self.assertTrue(L.material(["goal MAL-09 at 95 P is not below its value to us (91)"]))

    def test_votable_by_level(self):
        ch = ["goal SAL-04 up to 8 P", "goal MAL-09 up to 88 P", "avoid buying sets [] -> ['RET']",
              "cash policy {} -> {'reserve': 30}", "pause ['market']"]
        low = L.votable(ch, 40)
        self.assertEqual(low, ["goal MAL-09 up to 88 P", "cash policy {} -> {'reserve': 30}", "pause ['market']"])
        self.assertEqual(L.votable(ch, 60), ch)

    def test_vote_cache_and_offline(self):
        c = L.VoteCache()
        self.assertIsNone(c.get(["goal MAL-09 up to 88 P"], 100))
        c.put(["goal MAL-09 up to 88 P"], 100, {"ok": True, "yes": 3})
        self.assertEqual(c.get(["goal MAL-09 up to 88 P"], 120)["yes"], 3)
        self.assertIsNone(c.get(["goal MAL-09 up to 88 P"], 140))
        self.assertTrue(L.offline_vote(["goal MAL-09 up to 88 P"], "x")["ok"])
        self.assertFalse(L.offline_vote(["cash policy {} -> {'reserve': 5}"], "x")["ok"])

    def test_trading_council_gate(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            llm_rows(live, [])
            small = Act(params={"give": {"cash": 9}}, expected={"value_gain": 2})
            big = Act(params={"give": {"cash": 80}}, expected={"value_gain": 11})
            self.assertEqual(L.trading_council_gate(small, live, now=1000, level=40, council_target=2.0)[0], "approve")
            self.assertIsNone(L.trading_council_gate(small, live, now=1000, level=60, council_target=2.0))
            self.assertIsNone(L.trading_council_gate(big, live, now=1000, level=40, council_target=2.0))
            llm_rows(live, [{"ts": 900, "purpose": "council", "cost_usd": 3.0}])            # bucket empty (1.25 allowed)
            self.assertEqual(L.trading_council_gate(big, live, now=1000, level=40, council_target=2.0)[0], "approve")
            nogain = Act(params={"give": {"cash": 80}}, expected={})
            self.assertEqual(L.trading_council_gate(nogain, live, now=1000, level=40, council_target=2.0)[0], "veto")
            duel = Act(kind="duel_accept", params={"duel": 1})
            self.assertEqual(L.trading_council_gate(duel, live, now=1000, level=60, council_target=2.0)[0], "approve")


if __name__ == "__main__":
    unittest.main()
