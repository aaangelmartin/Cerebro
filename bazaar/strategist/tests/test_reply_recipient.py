import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bazaar.outbox import Outbox
from bazaar.strategist.run import Strategist


class ReplyRecipientTest(unittest.TestCase):
    def test_reply_goes_to_the_sender(self):
        with tempfile.TemporaryDirectory() as d:
            live, rec = Path(d) / "live", Path(d) / "record"
            live.mkdir(); rec.mkdir()
            box_path = live / "outbox.jsonl"
            records = [{"id": "abc123", "team": "t05", "author": "Daniel Suárez", "text": "accept 4167?"},
                       {"id": "def456", "team": "t15", "author": "equipo", "text": "26 for SAL-07"}]
            s = Strategist(live=live, record=rec, llm=None)
            plan = {"whatsapp_replies": [{"reply_to": "abc123", "text": "Done, accepted 4167.", "why": "x"},
                                         {"reply_to": "def456", "text": "Deal, SAL-07 at 26.", "why": "y"}]}
            with mock.patch("bazaar.outbox.store.DEFAULT_PATH", box_path), \
                    mock.patch.object(Strategist, "_external_records", return_value=records):
                s._whatsapp(plan, {"tick": 1})
            items = {i["text"]: i for i in Outbox(box_path).list("promo")}
            a, b = items["Done, accepted 4167."], items["Deal, SAL-07 at 26."]
            self.assertEqual((a["to_team"], a["to_person"], a["audience"]), ("t05", "Daniel Suárez", "person"))
            self.assertEqual((b["to_team"], b["to_person"], b["audience"]), ("t15", None, "team"))


if __name__ == "__main__":
    unittest.main()
