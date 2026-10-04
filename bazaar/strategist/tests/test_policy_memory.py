"""The brain's policy memory keeps the newest rules when it is full (Saturday night it kept the oldest 30)."""
import tempfile
import unittest
from pathlib import Path

from bazaar.strategist import brainio as B


class PolicyMemoryTest(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())

    def test_a_full_memory_drops_the_oldest_rule_not_the_new_one(self):
        for i in range(B.MAX_POLICIES):
            B.apply_policies(self.live, [{"text": f"old rule {i}"}], now=100.0 + i)
        got = B.apply_policies(self.live, [{"text": "Sunday plan: team deals first"}], now=900.0)
        pols = B.memory(self.live)["policies"]
        self.assertEqual(len(pols), B.MAX_POLICIES)
        self.assertIn(got[0]["id"], [p["id"] for p in pols])
        self.assertNotIn("old rule 0", [p["text"] for p in pols])
        self.assertIn("old rule 1", [p["text"] for p in pols])

    def test_retired_rules_leave_before_any_active_one(self):
        for i in range(B.MAX_POLICIES):
            B.apply_policies(self.live, [{"text": f"rule {i}"}], now=100.0 + i)
        B.apply_policies(self.live, [{"id": "P5", "status": "retired"}], now=800.0)      # newest update, but retired
        B.apply_policies(self.live, [{"text": "new rule"}], now=900.0)
        pols = B.memory(self.live)["policies"]
        self.assertNotIn("P5", [p["id"] for p in pols])
        self.assertIn("rule 0", [p["text"] for p in pols])
        self.assertEqual(sum(p["status"] == "active" for p in pols), B.MAX_POLICIES)

    def test_every_retired_rule_is_kept_while_there_is_room(self):
        for i in range(10):
            B.apply_policies(self.live, [{"text": f"rule {i}"}], now=100.0 + i)
        B.apply_policies(self.live, [{"id": f"P{i}", "status": "retired", "reason": "old"} for i in range(1, 7)],
                         now=500.0)
        pols = B.memory(self.live)["policies"]
        self.assertEqual(len(pols), 10)                                  # Sunday 04:00: 2 of 6 retired ones vanished
        self.assertEqual(sum(p["status"] == "retired" for p in pols), 6)

    def test_a_retirement_without_text_keeps_the_rule_readable(self):
        B.apply_policies(self.live, [{"text": "LAV-11 up to 130"}], now=1.0)
        B.apply_policies(self.live, [{"id": "P1", "status": "retired", "reason": "replaced by P112"}], now=2.0)
        p = B.memory(self.live)["policies"][0]
        self.assertEqual((p["status"], p["text"], p["reason"]), ("retired", "LAV-11 up to 130", "replaced by P112"))

    def test_a_number_the_brain_gives_is_kept(self):
        B.apply_policies(self.live, [{"text": "first"}], now=1.0)
        got = B.apply_policies(self.live, [{"id": "P112", "text": "Sunday v2"}, {"id": "", "text": "next"}], now=2.0)
        self.assertEqual([p["id"] for p in got], ["P112", "P113"])
        again = B.apply_policies(self.live, [{"id": "P112", "text": "Sunday v3"}], now=3.0)
        self.assertEqual(again[0]["text"], "Sunday v3")
        self.assertEqual(len(B.memory(self.live)["policies"]), 3)


if __name__ == "__main__":
    unittest.main()
