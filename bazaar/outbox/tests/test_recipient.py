import tempfile
import unittest
from pathlib import Path

from bazaar.outbox import Outbox, recipient, team_id


class RecipientTest(unittest.TestCase):
    def test_team_id(self):
        self.assertEqual([team_id(x) for x in ("t5", "T05", "Team 5", 12, None)], ["t05", "t05", "t05", "t12", None])

    def test_inferred_from_text(self):
        self.assertEqual(recipient("Team 5: quick ask before the h5.0 Market Test"),
                         {"to_team": "t05", "to_person": None, "audience": "team"})
        self.assertEqual(recipient("Hi Team 15! The offer is on v10")["to_team"], "t15")
        self.assertEqual(recipient("Thanks Team 15! SAL-07 went through")["to_team"], "t15")
        self.assertEqual(recipient("@Daniel: can you post publicly on v07?"),
                         {"to_team": None, "to_person": "Daniel", "audience": "person"})
        self.assertEqual(recipient("Team 10 opened its market v07: 0% fee")["audience"], "group")
        self.assertEqual(recipient("Sorry Team 15, the earlier offer lapsed.")["to_team"], "t15")
        self.assertEqual(recipient("Great, Team 15! SAL-07 is posted to you")["to_team"], "t15")
        self.assertEqual(recipient("Hola equipo 5: v07 no cobra comisión")["to_team"], "t05")
        self.assertEqual(recipient("Thanks! Our LAV page is complete. Team 5 asked first")["audience"], "group")
        self.assertEqual(recipient("Good morning traders, v07 is 0% fee"),
                         {"to_team": None, "to_person": None, "audience": "group"})

    def test_explicit_fields_win(self):
        self.assertEqual(recipient("Hi all", to_team="t5", audience="team"),
                         {"to_team": "t05", "to_person": None, "audience": "team"})
        self.assertEqual(recipient("Hi", to_team="t05", to_person="Daniel Suárez")["audience"], "person")

    def test_draft_promo_stores_and_backfills(self):
        with tempfile.TemporaryDirectory() as d:
            box = Outbox(Path(d) / "outbox.jsonl")
            it = box.draft_promo("Team 5: please post publicly on v07", "reciprocity")
            self.assertEqual((it["to_team"], it["audience"]), ("t05", "team"))
            old = box._put({"kind": "promo", "channel": "whatsapp", "text": "Hi Team 3, swap?", "why": "",
                            "status": "draft"})
            again = box.draft_promo("Hi Team 3, swap?")
            self.assertEqual((again["id"], again["to_team"], again["audience"]), (old["id"], "t03", "team"))


if __name__ == "__main__":
    unittest.main()
