"""The learning loop end to end, with fakes: a team chat hint -> brain policy -> Lab lesson -> the domains'
prompts and candidate filters change -> the hourly review compares what happened."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from bazaar import config
from bazaar.brain import strategy as S
from bazaar.core.goal import avoided
from bazaar.lab.run import Lab
from bazaar.lab.store import LessonStore
from bazaar.strategist import brainio as B
from bazaar.strategist.run import Strategist


class LearningLoopTest(unittest.TestCase):
    def test_chat_hint_becomes_behaviour(self):
        root = Path(tempfile.mkdtemp())
        live, lab_dir, rec = root / "live", root / "lab", root / "record"
        for d in (live, lab_dir, rec):
            d.mkdir()
        with mock.patch.object(config, "LAB", lab_dir), mock.patch.object(config, "LIVE", live):
            # 1. the team says it in the chat
            B.chat_post(live, "don't buy La Latina", by="equipo")
            # 2. the brain (Opus, faked) turns it into a policy and a plan setting
            pol = B.apply_policies(live, [{"text": "Do not buy La Latina (LAT) cards: low affinity, far from a page.",
                                           "from": "chat", "reason": "team hint, our LAT buys add little score"}])
            self.assertEqual(pol[0]["id"], "P1")
            plan = {"priorities": ["avoid LAT: 1/10 held, affinity 0.5"], "avoid_buy_sets": ["LAT"],
                    "expected_next_hour": {"score_delta": 1.0}}
            now = time.time()
            S.path(live).write_text(json.dumps({"updated": now, "tick": 400, "plan": plan}))
            S._cache.update(path=None, mtime=None, data=None)
            st = Strategist(live=live, record=rec)
            st._lab_loop(plan)
            self.assertTrue((lab_dir / "brain_input.json").exists())
            # 3. the Lab mirrors it as an active lesson
            lab = Lab(lab=lab_dir, live=live, use_llm=False)
            self.assertEqual(lab.ingest_brain(), ["BP1"])
            lesson = LessonStore(lab_dir / "lessons.jsonl").get("BP1")
            self.assertEqual((lesson.status, lesson.scope, lesson.created_by), ("active", "market", "cerebro"))
            # 4. the market prompt carries it and LAT buy candidates are excluded
            self.assertIn("La Latina", LessonStore(lab_dir / "lessons.jsonl").prompt_block_for(["market"]))
            control = S.overlay({}, live)
            self.assertIn("LAT", control["avoid_buy_sets"])
            self.assertTrue(avoided("LAT-03", control))
            self.assertFalse(avoided("MAL-09", control))
            # 5. an hour later the review compares the expectation with what happened
            with (live / "strategy.jsonl").open("a") as f:
                f.write(json.dumps({"updated": now - 3700, "tick": 300, "plan": plan,
                                    "score_at_plan": {"score": 20.0}}) + "\n")
            row = B.hourly_review(live, {"tick": 420, "us_now": {"score": 21.5}}, now=now)
            self.assertEqual(row["realised"]["score"], 1.5)
            self.assertIn("expected +1.00, got +1.50", row["verdict"])
            self.assertTrue((live / "strategist_reviews.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
