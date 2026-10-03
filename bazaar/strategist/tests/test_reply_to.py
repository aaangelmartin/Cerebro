import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from bazaar.strategist.brainio import resolve_reply_to

MAD = ZoneInfo("Europe/Madrid")
T1 = datetime(2026, 10, 3, 11, 6, 10, tzinfo=MAD).timestamp()
T2 = datetime(2026, 10, 3, 11, 9, 0, tzinfo=MAD).timestamp()
RECS = [{"id": "x1", "ts": T1, "author": "Daniel Suárez", "team": "t05"},
        {"id": "x2", "ts": T2, "author": "Lucía", "team": "t12"}]


class ReplyToTest(unittest.TestCase):
    def test_id(self):
        self.assertEqual(resolve_reply_to("x2", RECS), "x2")
        self.assertEqual(resolve_reply_to("[x1]", RECS), "x1")

    def test_time_label(self):
        self.assertEqual(resolve_reply_to("11:06", RECS), "x1")
        self.assertIsNone(resolve_reply_to("10:00", RECS))

    def test_author_or_team(self):
        self.assertEqual(resolve_reply_to("Daniel Suárez", RECS), "x1")
        self.assertEqual(resolve_reply_to("t12", RECS), "x2")

    def test_ambiguous(self):
        both = RECS + [{"id": "x3", "ts": T1 + 20, "author": "Daniel Suárez", "team": "t05"}]
        self.assertIsNone(resolve_reply_to("11:06", both))
        self.assertIsNone(resolve_reply_to("Daniel", both))


if __name__ == "__main__":
    unittest.main()
