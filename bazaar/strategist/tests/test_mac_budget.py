"""The Mac backend is budgeted by calls per hour, not dollars: governor, gaps, settings, budget split."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.strategist import budget as BG
from bazaar.strategist import limiter as L

OPEN = {"paused": False, "doors": "open", "t_hours": 7.0, "tick_seconds": 30.0}


class MacGovernorTest(unittest.TestCase):
    def test_default_level_is_70_and_counts_calls(self):
        level, why = BG.govern_mac(clock=OPEN, calls_last_hour=5, cap=60)
        self.assertEqual(level, 70)
        self.assertIn("5/60", why)

    def test_boosts_and_cuts(self):
        self.assertEqual(BG.govern_mac(clock=OPEN, calls_last_hour=5, cap=60, signals={"bargain": True})[0], 95)
        self.assertEqual(BG.govern_mac(clock=OPEN, calls_last_hour=5, cap=60, signals={"duels_live": True})[0], 85)
        self.assertEqual(BG.govern_mac(clock=OPEN, calls_last_hour=5, cap=60, signals={"unchanged": True})[0], 50)
        soon = [{"at_hours": 7.1, "action": "bench"}]
        self.assertEqual(BG.govern_mac(clock=OPEN, calls_last_hour=5, cap=60, upcoming=soon)[0], 85)

    def test_slows_down_near_the_hourly_cap(self):
        self.assertEqual(BG.govern_mac(clock=OPEN, calls_last_hour=44, cap=60, signals={"bargain": True})[0], 55)
        self.assertEqual(BG.govern_mac(clock=OPEN, calls_last_hour=56, cap=60)[0], 40)

    def test_paused_or_closed_is_zero(self):
        self.assertEqual(BG.govern_mac(clock={**OPEN, "paused": True}, calls_last_hour=0, cap=60)[0], 0)
        self.assertEqual(BG.govern_mac(clock={**OPEN, "doors": "closed"}, calls_last_hour=0, cap=60)[0], 0)


class MacSettingsTest(unittest.TestCase):
    def test_mac_settings_are_fuller_and_faster(self):
        api, mac = BG.settings(70), BG.settings(70, mac=True)
        self.assertEqual(mac["backend"], "mac")
        self.assertGreater(mac["picture_chars"], api["picture_chars"])
        self.assertLessEqual(mac["interval_ticks"], 4)
        self.assertEqual(mac["max_reasks"], 1)
        self.assertEqual(mac["min_gap_s"], 100)
        self.assertEqual(L.min_gap_s(70), 120)                 # the API gap is unchanged
        self.assertEqual(L.min_gap_s(40, mac=True), 240)

    def test_count_bucket(self):
        self.assertTrue(L.mac_gate(10, 60)["ok"])
        self.assertFalse(L.mac_gate(60, 60)["ok"])
        self.assertFalse(L.mac_gate(55, 60, weight=1, reserve=6)["ok"])    # the reserve is for votes and chat
        self.assertTrue(L.mac_gate(55, 60, weight=1, reserve=0)["ok"])
        self.assertFalse(L.mac_gate(57, 60, weight=5)["ok"])              # a research session weighs 5
        self.assertEqual(L.mac_gate(57, 60)["left"], 3)

    def test_gate_uses_the_mac_gap(self):
        base = dict(now=1000.0, level=70, last_plan_ts=890.0, has_chat=False)
        self.assertFalse(L.gate(**base)["ok"])                             # 110 s < 120 s on the API
        self.assertTrue(L.gate(**base, gap_s=L.min_gap_s(70, mac=True))["ok"])
        full = {"ok": False, "spent": 60, "allowed": 60}
        self.assertFalse(L.gate(**base, gap_s=100, strategy_bucket=full)["ok"])   # the count bucket still stops it


class BudgetSplitTest(unittest.TestCase):
    def test_report_separates_api_dollars_from_mac_calls(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            now = time.time()
            (live / "control.json").write_text(json.dumps({"brain_backend": "auto", "mac_calls_per_hour": 60}))
            (live / "mac_backend.json").write_text(json.dumps(
                {"calls": [now - 100, now - 50, now - 5000], "calls_total": 9, "reported_usd": 3.21}))
            rep = BG.report(live, clock=OPEN, spend={"usd": 80.0, "by_purpose": {"strategy": 50.3}, "by_key": {}}, now=now)
            self.assertEqual(rep["brain_api_usd_today"], 50.3)
            self.assertEqual(rep["mac_calls_last_hour"], 2)
            self.assertEqual(rep["mac_calls_today"], 9)
            self.assertEqual(rep["mac_saved_usd_estimate"], 3.21)
            self.assertEqual(rep["mac_calls_per_hour"], 60)
            self.assertIn(rep["mac_backend_state"], ("ok", "missing"))
            if rep["brain_on_mac"]:
                self.assertEqual(rep["usd_per_hour_level"], 0.0)       # Mac plans cost no API dollars
                self.assertEqual(rep["settings"]["backend"], "mac")
            self.assertLessEqual(rep["projected_spend_by_close"], rep["cap_today"])


if __name__ == "__main__":
    unittest.main()
