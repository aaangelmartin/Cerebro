import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar.strategist.run import Strategist


class ThinkingHeartbeatTest(unittest.TestCase):
    def test_thinking_fields_set_during_call_and_cleared_after(self):
        with tempfile.TemporaryDirectory() as d:
            live, rec = Path(d) / "live", Path(d) / "record"
            live.mkdir(); rec.mkdir()
            st = Strategist(live=live, record=rec, llm=object())
            p = live / "strategist_status.json"
            with st.thinking("chat", every_s=0.05):
                first = json.loads(p.read_text())
                self.assertEqual(first["thinking_reason"], "chat")
                self.assertIsNotNone(first["thinking_since"])
                time.sleep(0.2)                       # the background beat keeps `updated` fresh
                later = json.loads(p.read_text())
                self.assertGreater(later["updated"], first["updated"])
            done = json.loads(p.read_text())
            self.assertIsNone(done["thinking_since"])
            self.assertIsNone(done["thinking_reason"])

    def test_cleared_even_when_the_call_fails(self):
        with tempfile.TemporaryDirectory() as d:
            live, rec = Path(d) / "live", Path(d) / "record"
            live.mkdir(); rec.mkdir()
            st = Strategist(live=live, record=rec, llm=object())
            with self.assertRaises(RuntimeError):
                with st.thinking("scheduled"):
                    raise RuntimeError("api down")
            done = json.loads((live / "strategist_status.json").read_text())
            self.assertIsNone(done["thinking_since"])

    def test_label_prefers_chat_then_events(self):
        with tempfile.TemporaryDirectory() as d:
            live, rec = Path(d) / "live", Path(d) / "record"
            live.mkdir(); rec.mkdir()
            st = Strategist(live=live, record=rec, llm=object())
            st.pending_events = [{"kind": "score"}, {"kind": "chat"}]
            self.assertEqual(st._thinking_label("x"), "chat")
            st.pending_events = [{"kind": "score"}]
            self.assertEqual(st._thinking_label("x"), "event: score")
            st.pending_events = []
            self.assertEqual(st._thinking_label("every 4 ticks"), "every 4 ticks")


if __name__ == "__main__":
    unittest.main()
