import json
import tempfile
import unittest
from pathlib import Path

from bazaar.lab.run import Lab


class BrainIngestTest(unittest.TestCase):
    def test_policies_become_lessons_and_retire(self):
        with tempfile.TemporaryDirectory() as d:
            lab_dir, live = Path(d) / "lab", Path(d) / "live"
            lab_dir.mkdir(); live.mkdir()
            lab = Lab(lab=lab_dir, live=live, use_llm=False)
            pol = {"id": "P3", "text": "Never post swaps that want cards from avoided sets (LAT, RET).",
                   "status": "active", "reason": "sanity check"}
            (lab_dir / "brain_input.json").write_text(json.dumps({"policies": [pol]}))
            self.assertEqual(lab.ingest_brain(), ["BP3"])
            l = lab.store.get("BP3")
            self.assertEqual((l.status, l.scope, l.created_by), ("active", "market", "cerebro"))
            self.assertEqual(lab.ingest_brain(), [])                   # unchanged: nothing rewritten
            (lab_dir / "brain_input.json").write_text(json.dumps({"policies": [{**pol, "status": "retired"}]}))
            self.assertEqual(lab.ingest_brain(), ["BP3"])
            self.assertEqual(lab.store.get("BP3").status, "retired")


if __name__ == "__main__":
    unittest.main()
