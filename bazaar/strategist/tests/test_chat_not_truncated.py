"""A team chat directive reaches the brain's EVENTS whole (code-45476519)."""
import tempfile
import unittest
from pathlib import Path

from bazaar.strategist import brainio as B
from bazaar.strategist.run import _wrap


class ChatNotTruncated(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())

    def test_long_directive_is_stored_and_logged_whole(self):
        text = "DIRECTIVE from Daniel. " + "Each rule has a number 57. " * 80 + "LAST RULE: sell at 87."
        self.assertGreater(len(text), 2000)
        row = B.chat_post(self.live, text, by="Daniel")
        self.assertEqual(row["text"], text)
        ev = B.log_event(self.live, "chat", "Daniel: " + _wrap(row["text"], "team-chat", B.CHAT_MAX_CHARS + 120), 1018)
        self.assertIn("LAST RULE: sell at 87.", ev["text"])
        self.assertTrue(ev["text"].endswith("</untrusted>"))

    def test_a_message_over_the_cap_says_it_was_cut(self):
        row = B.chat_post(self.live, "x" * (B.CHAT_MAX_CHARS + 250), by="Daniel")
        self.assertIn("[cut: 250 more characters", row["text"])
        ev = B.log_event(self.live, "chat", "Daniel: " + _wrap(row["text"], "team-chat", B.CHAT_MAX_CHARS + 120), 1)
        self.assertIn("[cut: 250 more characters", ev["text"])

    def test_other_events_keep_the_short_cap(self):
        ev = B.log_event(self.live, "dealer", "y" * 900, 1)
        self.assertEqual(len(ev["text"]), 400)


if __name__ == "__main__":
    unittest.main()
