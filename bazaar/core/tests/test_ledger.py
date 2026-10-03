import tempfile
import threading
import time
import unittest

from bazaar.core.ledger import Ledger
from bazaar.core.types import Action, Outcome, Verdict


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.lg = Ledger(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_ids_and_tail(self):
        for i in range(10):
            self.lg.append("events", {"n": i})
        self.assertEqual([r["n"] for r in self.lg.tail("events", limit=3)], [7, 8, 9])
        self.assertEqual([r["id"] for r in self.lg.tail("events", since_id=8)], [9, 10])
        again = Ledger(self.dir.name)                   # ids continue after a restart
        self.assertEqual(again.append("events", {"n": 10})["id"], 11)
        self.assertEqual(self.lg.tail("nothing"), [])

    def test_threads_do_not_interleave(self):
        def work(k):
            for i in range(50):
                self.lg.append("decisions", {"k": k, "i": i, "pad": "x" * 500})
        ts = [threading.Thread(target=work, args=(k,)) for k in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        recs = self.lg.tail("decisions", limit=1000)
        self.assertEqual(len(recs), 200)
        self.assertEqual(sorted(r["id"] for r in recs), list(range(1, 201)))

    def test_skips_broken_lines(self):
        self.lg.append("llm", {"a": 1})
        with self.lg.path("llm").open("a") as f:
            f.write("{broken\n")
        self.lg.append("llm", {"a": 2})
        self.assertEqual([r.get("a") for r in self.lg.tail("llm")], [1, 2])

    def test_spend_and_deals(self):
        now = time.time()
        a = Action("accept_offer", {"offer": 1}, "market")
        self.lg.outcome(Outcome(a.id, 1, "sent", {}, {"cash_out": 30, "counterparty": "t3"}), a)
        self.lg.outcome(Outcome(a.id, 2, "deal", {}, {"cash_out": 30, "counterparty": "t3"}), a)   # same action
        self.lg.outcome(Outcome("b", 2, "sent", {}, {"cash_out": 20, "counterparty": "t3"}))
        self.lg.outcome(Outcome("c", 2, "refused", {}, {"cash_out": 99, "counterparty": "t3"}))
        self.lg.append("outcomes", {"ts": now - 7200, "action_id": "old", "status": "sent",
                                    "realised": {"cash_out": 500, "counterparty": "t3"}})
        self.assertEqual(self.lg.spend_last_hour(), 0)  # the old record is last in the file: stops the scan
        self.lg.outcome(Outcome("d", 3, "sent", {}, {"cash_out": 5, "counterparty": "t4"}))
        self.assertEqual(self.lg.spend_last_hour(), 5)

    def test_spend_window(self):
        a = Action("accept_offer", {"offer": 1}, "market")
        self.lg.outcome(Outcome(a.id, 1, "sent", {}, {"cash_out": 30, "counterparty": "t3"}), a)
        self.lg.outcome(Outcome(a.id, 2, "deal", {}, {"cash_out": 30, "counterparty": "t3"}), a)
        self.lg.outcome(Outcome("b", 2, "sent", {}, {"cash_out": 20, "counterparty": "t3"}))
        self.lg.outcome(Outcome("c", 2, "refused", {}, {"cash_out": 99, "counterparty": "t3"}))
        self.assertEqual(self.lg.spend_last_hour(), 50)
        self.assertEqual(self.lg.deals_with("t3"), 2)
        self.assertEqual(self.lg.deals_with("t9"), 0)

    def test_decision(self):
        a = Action("noop", {}, "lab")
        rec = self.lg.decision(a, Verdict(False, "cash", "x"), latency_s=0.2, tick=5)
        self.assertEqual(rec["verdict"]["rail"], "cash")
        self.assertEqual(self.lg.tail("decisions")[-1]["action"]["kind"], "noop")


if __name__ == "__main__":
    unittest.main()
