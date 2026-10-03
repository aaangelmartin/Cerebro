import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from bazaar.strategist import budget as BG
from bazaar.strategist.run import split_picture


def clock(hours_left=8.0, paused=False, tick=30.0, today="sat"):
    now = time.time()
    closes = datetime.fromtimestamp(now + hours_left * 3600).astimezone().isoformat()
    sun_open = datetime.fromtimestamp(now + 18 * 3600).astimezone()
    return {"tick": 700, "t_hours": 7.0, "tick_seconds": tick, "paused": paused, "doors": "open", "today": today,
            "closes": closes,
            "days": [{"day": "sun", "opens": sun_open.isoformat(), "closes": (sun_open + timedelta(hours=6)).isoformat(),
                      "tick_seconds": 15.0}]}


UPCOMING = [{"at_hours": 9.0, "action": "bench"}, {"at_hours": 11.65, "action": "duels"},
            {"at_hours": 14.08, "action": "day_closes"}, {"at_hours": 14.65, "action": "bench"},
            {"at_hours": 18.65, "action": "duels"}, {"at_hours": 21.65, "action": "duels"}]


class MappingTest(unittest.TestCase):
    def test_anchors_and_monotonic(self):
        self.assertEqual([BG.settings(l)["interval_ticks"] for l in (0, 50, 100)], [20, 8, 3])
        prev = None
        for lv in range(0, 101, 5):
            s = BG.settings(lv)
            cost = BG.estimate_usd_per_hour(lv)
            if prev:
                self.assertLessEqual(s["interval_ticks"], prev[0]["interval_ticks"])
                self.assertGreaterEqual(s["picture_chars"], prev[0]["picture_chars"])
                self.assertGreaterEqual(len(s["wake_kinds"]), len(prev[0]["wake_kinds"]))
                self.assertGreaterEqual(cost, prev[1])
            prev = (s, cost)
        self.assertEqual(set(BG.settings(0)["wake_kinds"]), set(BG.ALWAYS_KINDS))
        self.assertIn("score", BG.settings(100)["wake_kinds"])

    def test_level_for_budget_fits(self):
        for usd in (3, 5, 9):
            lv = BG.level_for_budget(usd)
            self.assertLessEqual(BG.estimate_usd_per_hour(lv), usd)
        self.assertEqual(BG.level_for_budget(0.1), 0)


class CostModelTest(unittest.TestCase):
    def test_measured_from_llm_log(self):
        with tempfile.TemporaryDirectory() as d:
            now = time.time()
            rows = [{"ts": now - 60 * i, "purpose": "strategy", "cost_usd": 0.30} for i in range(5)]
            rows += [{"ts": now - 60 * i, "purpose": "council", "cost_usd": 0.05} for i in range(4)]
            rows += [{"ts": now - 9 * 3600, "purpose": "strategy", "cost_usd": 9.0}]            # too old
            (Path(d) / "llm.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            m = BG.measured(Path(d), now)
            self.assertEqual((m["plan_usd"], m["plans_measured"], m["council_usd"]), (0.3, 5, 0.05))
            self.assertLess(BG.estimate_usd_per_hour(0, 30, m), BG.estimate_usd_per_hour(100, 30, m))
            self.assertEqual(len(BG.table(30, m)), 11)

    def test_defaults_without_data(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(BG.measured(Path(d))["plan_usd"], BG.DEFAULT_PLAN_USD)


class EventPlanTest(unittest.TestCase):
    def plan(self, **kw):
        base = dict(clock=clock(), upcoming=UPCOMING, days_spent={"fri": {"usd": 9.0},
                    "sat": {"usd": 65.0, "by_purpose": {"strategy": 40.0, "council": 10.0, "duels": 6.0}}}, total=220.0)
        base.update(kw)
        return BG.event_plan(**base)

    def test_split_adds_up_and_reserves_sessions(self):
        p = self.plan()
        self.assertEqual(p["spent_total"], 65.0)                       # Friday is not part of this budget
        self.assertEqual(p["remaining_total"], 155.0)
        self.assertAlmostEqual(p["left_today"] + p["plan_tomorrow"], 155.0, places=1)
        self.assertEqual(p["sessions"], {"duels_today": 1, "bench_today": 1, "duels_tomorrow": 2, "bench_tomorrow": 1})
        self.assertGreater(p["plan_tomorrow"], BG.RESERVE_DUELS_USD * 2)       # Sunday keeps its duel sessions
        self.assertGreater(p["plan_today"], 65.0)
        self.assertLessEqual(p["brain_left_today"], BG.BRAIN_SHARE_MAX * p["left_today"] + 0.01)
        self.assertAlmostEqual(p["purpose_caps"]["duels"], 6.0 + 15.0, places=2)

    def test_sunday_gets_everything_left(self):
        p = self.plan(clock=clock(hours_left=6, tick=15.0, today="sun"), upcoming=[{"at_hours": 8.0, "action": "duels"}],
                      days_spent={"sat": {"usd": 140.0}, "sun": {"usd": 10.0, "by_purpose": {"strategy": 4.0}}})
        self.assertEqual(p["remaining_total"], 70.0)
        self.assertEqual(p["plan_tomorrow"], 0.0)
        self.assertAlmostEqual(p["left_today"], 70.0, places=1)

    def test_unspent_saturday_carries_over(self):
        thrifty = self.plan(days_spent={"sat": {"usd": 40.0}})
        spender = self.plan(days_spent={"sat": {"usd": 120.0}})
        self.assertGreater(thrifty["plan_tomorrow"], spender["plan_tomorrow"])

    def test_overspent_budget_never_negative(self):
        p = self.plan(days_spent={"sat": {"usd": 300.0}})
        self.assertEqual((p["remaining_total"], p["left_today"], p["brain_left_today"]), (0.0, 0.0, 0.0))


class GovernorTest(unittest.TestCase):
    def test_paused_or_closed_is_zero(self):
        self.assertEqual(BG.govern(clock=clock(paused=True), spent=0, cap=60)[0], 0)
        self.assertEqual(BG.govern(clock={**clock(), "doors": "closed"}, spent=0, cap=60)[0], 0)
        self.assertEqual(BG.govern(clock=clock(), spent=60, cap=60)[0], 0)

    def test_paces_the_budget(self):
        rich, _ = BG.govern(clock=clock(hours_left=2), spent=0, cap=60)
        poor, _ = BG.govern(clock=clock(hours_left=8), spent=50, cap=60)
        self.assertGreater(rich, poor)
        self.assertLessEqual(BG.estimate_usd_per_hour(poor), max(10 / 8 * 2, BG.estimate_usd_per_hour(5)))

    def test_activity_raises_and_quiet_lowers(self):
        base, _ = BG.govern(clock=clock(), spent=20, cap=60)
        hot, why = BG.govern(clock=clock(), spent=20, cap=60, signals={"bargain": True})
        quiet, _ = BG.govern(clock=clock(), spent=20, cap=60, signals={"unchanged": True})
        soon, why2 = BG.govern(clock=clock(), spent=20, cap=60, upcoming=[{"at_hours": 7.1, "action": "duels"}])
        self.assertGreater(hot, base)
        self.assertIn("bargain", why)
        self.assertLess(quiet, base)
        self.assertGreater(soon, base)
        self.assertIn("duels", why2)


class ControlTest(unittest.TestCase):
    def test_valid(self):
        out = BG.validate_control({"brain_intensity": 72.4, "brain_intensity_mode": "manual", "brain_day_cap": 80,
                                   "day_cap": 150, "budget_total_usd": 220, "other": 1})
        self.assertEqual(out.pop("caps_day"), BG.config.madrid_day())
        self.assertEqual(out, {"brain_intensity": 72, "brain_intensity_mode": "manual", "brain_day_cap": 80.0,
                               "day_cap": 150.0, "budget_total_usd": 220.0})
        self.assertEqual(BG.brain_day_cap({"brain_day_cap": 80, "caps_day": "xxx"}, Path("/nonexistent")),
                         BG.BRAIN_CAP_DEFAULT)                      # yesterday's hand-set cap no longer applies
        self.assertEqual(BG.validate_control({"day_cap": None, "brain_day_cap": None}),
                         {"day_cap": None, "brain_day_cap": None})

    def test_invalid(self):
        for bad in ({"brain_intensity": 101}, {"brain_intensity": True}, {"brain_intensity_mode": "turbo"},
                    {"brain_day_cap": 500}, {"day_cap": 999}, {"budget_total_usd": 5000}):
            with self.assertRaises(ValueError):
                BG.validate_control(bad)

    def test_caps_from_control_are_clamped(self):
        self.assertEqual(BG.brain_day_cap({"brain_day_cap": 9999}), BG.BRAIN_CAP_MAX)
        self.assertEqual(BG.budget_total({"budget_total_usd": 1}), BG.TOTAL_MIN)
        self.assertEqual(BG.mode({"brain_intensity_mode": "x"}), "auto")
        self.assertEqual(BG.manual_level({"brain_intensity": 30}), 30)


class PictureTest(unittest.TestCase):
    def test_reference_split_and_trim_keeps_core(self):
        pic = {"clock": {"tick": 1}, "us": {"cash": 5}, "policies": ["p"] * 50, "chat_recent": [{"t": "x" * 200}] * 80,
               "research": {"scoreboard": ["s" * 100] * 200, "gap": 1}}
        ref, live = split_picture(pic, 6000)
        self.assertIn("policies", ref)
        self.assertNotIn("policies", live)
        self.assertEqual((live["clock"], live["us"]), ({"tick": 1}, {"cash": 5}))
        self.assertLessEqual(len(json.dumps(live)), 6500)
        self.assertIn("chat_recent", live["picture_trimmed"])
        ref2, _ = split_picture(pic, 40000)
        self.assertEqual(json.dumps(ref, sort_keys=True), json.dumps(ref2, sort_keys=True))    # cache-stable


if __name__ == "__main__":
    unittest.main()
