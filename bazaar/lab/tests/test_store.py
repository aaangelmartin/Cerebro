import json
import tempfile
import threading
import unittest
from pathlib import Path

from bazaar.core.types import Lesson, Outcome
from bazaar.lab.store import CANARY_WEIGHT, LessonStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def L(id, scope="duel", status="active", weight=0.7, rule="r"):
    return Lesson(id=id, scope=scope, rule=rule, status=status, weight=weight)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.clock = Clock()
        self.s = LessonStore(self.dir / "lessons.jsonl", clock=self.clock)

    def test_active_scopes_and_order(self):
        self.s.upsert_many([L("a", weight=0.6), L("b", weight=0.9), L("c", status="proposed"),
                            L("d", scope="dealer", weight=0.7), L("e", scope="dealer:abuela", status="canary", weight=0.3),
                            L("g", scope="global", weight=0.8)])
        self.assertEqual([l.id for l in self.s.active("duel")], ["b", "a"])
        self.assertEqual([l.id for l in self.s.active("dealer:abuela")], ["d", "e"])
        block = self.s.prompt_block("duel")
        self.assertIn("[b ", block)
        self.assertIn("[g ", block)            # global lessons ride along
        self.assertNotIn("[c ", block)         # proposed never reaches the operator

    def test_versioned_jsonl_last_line_wins(self):
        self.s.upsert(L("a", rule="one"))
        self.s.upsert(L("a", rule="two"))
        rows = [json.loads(x) for x in (self.dir / "lessons.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        again = LessonStore(self.dir / "lessons.jsonl")
        self.assertEqual(again.get("a").rule, "two")
        self.assertEqual(again.get("a").version, 2)

    def test_prompt_block_cached_until_change_or_15_min(self):
        self.s.upsert(L("a", rule="first"))
        b1 = self.s.prompt_block("duel")
        # weight-only change (record_use) does not rebuild
        self.s.record_use(["a"], Outcome(action_id="x", tick=1, status="deal"))
        self.assertIs(self.s.prompt_block("duel"), b1)
        # content change rebuilds at once
        self.s.upsert(L("a", rule="second"))
        self.assertIn("second", self.s.prompt_block("duel"))
        b2 = self.s.prompt_block("duel")
        self.clock.t += 16 * 60
        b3 = self.s.prompt_block("duel")
        self.assertEqual(b2, b3)
        self.assertIsNot(b2, b3)               # rebuilt after 15 minutes

    def test_record_use_moves_weight_and_retires(self):
        self.s.upsert(L("a", weight=0.6))
        self.s.record_use(["a"], Outcome(action_id="x", tick=1, status="deal", realised={"points_delta": 3}))
        up = self.s.get("a").weight
        self.assertGreater(up, 0.6)
        for i in range(60):
            self.s.record_use(["a"], Outcome(action_id=str(i), tick=1, status="no_deal"))
        a = self.s.get("a")
        self.assertEqual(a.status, "retired")
        notices = (self.dir / "notices.jsonl").read_text()
        self.assertIn("retirada", notices)

    def test_canary_capped(self):
        self.s.upsert(L("c", status="canary", weight=CANARY_WEIGHT))
        for i in range(20):
            self.s.record_use(["c"], {"action_id": str(i), "tick": 1, "status": "deal"})
        self.assertLessEqual(self.s.get("c").weight, CANARY_WEIGHT)

    def test_neutral_outcomes_ignored(self):
        self.s.upsert(L("a", weight=0.6))
        self.s.record_use(["a"], Outcome(action_id="x", tick=1, status="sent"))
        self.assertEqual(self.s.get("a").weight, 0.6)

    def test_set_status_writes_notice(self):
        self.s.upsert(L("p", status="proposed", weight=0))
        l = self.s.set_status("p", "canary", by="gate")
        self.assertEqual(l.weight, CANARY_WEIGHT)
        n = [json.loads(x) for x in (self.dir / "notices.jsonl").read_text().splitlines()]
        self.assertEqual(n[-1]["to"], "canary")

    def test_bad_scope_refused(self):
        with self.assertRaises(ValueError):
            self.s.upsert(L("x", scope="rails"))

    def test_thread_safe_appends(self):
        self.s.upsert(L("a", weight=0.6))

        def work():
            for i in range(20):
                self.s.record_use(["a"], Outcome(action_id=str(i), tick=1, status="deal"))
        ts = [threading.Thread(target=work) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        lines = (self.dir / "lessons.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 81)
        for line in lines:
            json.loads(line)

    def test_reload_sees_other_writer(self):
        other = LessonStore(self.dir / "lessons.jsonl")
        other.upsert(L("z"))
        self.assertIsNotNone(self.s.get("z"))


if __name__ == "__main__":
    unittest.main()
