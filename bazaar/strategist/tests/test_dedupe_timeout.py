import tempfile
import unittest
from pathlib import Path

from bazaar.intel import external
from bazaar.llm import client
from bazaar.strategist import brainio as B


class TimeoutTest(unittest.TestCase):
    def test_brain_purposes_wait_longer(self):
        self.assertEqual(client.call_timeout("strategy"), 150.0)
        self.assertEqual(client.call_timeout("brain_eval"), 150.0)
        self.assertEqual(client.call_timeout("duels"), client.DEFAULT_TIMEOUT_S)


class ChatDedupeTest(unittest.TestCase):
    def test_double_submit_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            a = B.chat_post(Path(d), "no compres Retiro", by="angel", now=1000.0)
            b = B.chat_post(Path(d), "no compres Retiro", by="angel", now=1004.0)
            self.assertTrue(b.get("duplicate"))
            self.assertEqual(b["ts"], a["ts"])
            c = B.chat_post(Path(d), "no compres Retiro", by="angel", now=1030.0)   # later: a real repeat
            self.assertFalse(c.get("duplicate"))
            self.assertEqual(len(B.chat_since(Path(d))), 2)

    def test_brain_replies_are_not_deduped(self):
        with tempfile.TemporaryDirectory() as d:
            B.chat_post(Path(d), "ok", role="brain", now=1000.0)
            self.assertFalse(B.chat_post(Path(d), "ok", role="brain", now=1001.0).get("duplicate"))


class ExternalDedupeTest(unittest.TestCase):
    def test_headerless_paste_twice(self):
        with tempfile.TemporaryDirectory() as d:
            r1 = external.ingest("Team 5 here: please accept bid 4167", by="angel", live_dir=d, now=2000.0)
            r2 = external.ingest("Team 5 here: please accept bid 4167", by="angel", live_dir=d, now=2003.0)
            self.assertEqual(len(r1["added"]), 1)
            self.assertEqual((len(r2["added"]), r2["duplicates"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
