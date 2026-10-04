import tempfile
import unittest
from pathlib import Path

from bazaar.outbox.store import Outbox, seed_examples, similar


class OutboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.box = Outbox(Path(self.tmp.name) / "outbox.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_request_dedupes_and_counts(self):
        a = self.box.file_code("Broker probe sends prices outside the ask/bid range", ["t207 refused"],
                               "probe below ask", "only cross pairs", severity="high")
        b = self.box.file_code("Broker probe sends prices outside the ask / bid range!", ["t211 refused"],
                               "same", "same")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(b["occurrences"], 2)
        self.assertEqual(b["evidence"], ["t207 refused", "t211 refused"])
        self.assertEqual(len(self.box.list("code")), 1)

    def test_closed_request_reopens_when_it_recurs(self):
        a = self.box.file_code("Announcement retried every tick", ["t202"], "d", "p")
        self.box.update(a["id"], status="done", note="fixed in abc")
        again = self.box.file_code("Announcement retried every tick", ["t300"], "d", "p")
        self.assertEqual(again["status"], "open")
        self.assertTrue(again["recurred"])
        self.assertEqual(again["human_note"], "fixed in abc")

    def test_different_requests_stay_apart(self):
        self.box.file_code("Key router ignores workspace errors", [], "d", "p")
        self.box.file_code("Broker probe outside ask/bid", [], "d", "p")
        self.assertEqual(len(self.box.list("code")), 2)
        self.assertFalse(similar("Key router ignores workspace errors", "Broker probe outside ask/bid"))

    def test_update_validates_status_and_filters(self):
        p = self.box.draft_promo("Come to v07", why="volume")
        with self.assertRaises(ValueError):
            self.box.update(p["id"], status="done")
        self.box.update(p["id"], status="sent")
        self.assertEqual(self.box.list("promo", "sent")[0]["id"], p["id"])
        self.assertEqual(self.box.list("promo", "draft"), [])
        self.assertEqual(self.box.draft_promo("Come to  v07")["id"], p["id"])   # same text, one draft
        with self.assertRaises(KeyError):
            self.box.update("nope", status="sent")

    def test_since_and_order(self):
        t = self.box.file_task("Restart the tunnel", why="URL died")
        later = self.box.file_task("Rotate key C", why="cap")
        self.assertEqual([x["id"] for x in self.box.list("task")][0], later["id"])
        self.assertEqual(self.box.list(since=float(later["updated"])), [])
        self.box.update(t["id"], status="done")
        self.assertEqual(self.box.list("task", since=float(later["updated"]))[0]["id"], t["id"])

    def test_seed_is_idempotent(self):
        first = seed_examples(self.box)
        self.assertEqual(len(first), 5)
        self.assertEqual(seed_examples(self.box), [])
        kinds = {it["kind"] for it in self.box.list()}
        self.assertEqual(kinds, {"code", "promo", "task"})
        self.assertEqual(self.box.get("code-sat-router-400")["status"], "done")
        self.assertEqual(self.box.get("code-sat-broker-probe")["status"], "open")
        self.assertIn("broker probe", self.box.summary_text().lower())

    def test_tolerates_broken_lines(self):
        self.box.file_task("Restart the tunnel")
        with open(self.box.path, "a") as f:
            f.write('{"op": "put", "item": {"id"')
        self.assertEqual(len(self.box.list()), 1)


if __name__ == "__main__":
    unittest.main()
