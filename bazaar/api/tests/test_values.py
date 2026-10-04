import json
import tempfile
import unittest
from pathlib import Path

from bazaar.api.values import build


class CardValuesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.record, self.live = root / "record", root / "live"
        (self.record / "latest").mkdir(parents=True)
        self.live.mkdir()
        me = {"affinity": {"MAL": 1.3, "SAL": 0.9}, "assets": [
            {"id": 1, "kind": "card", "ref": "MAL-02", "your_value": 13.0},
            {"id": 2, "kind": "card", "ref": "MAL-02", "your_value": 3.3},
            {"id": 3, "kind": "pack", "ref": None}]}
        catalog = {"rarities": {"common": {"book": 10}, "rare": {"book": 70}}, "sets": [
            {"id": "MAL", "released": True, "cards": [
                {"id": "MAL-02", "rarity": "common", "name": "Plaza", "page": True},
                {"id": "MAL-09", "rarity": "rare", "name": "Heroina", "page": True},
                {"id": "MAL-11", "rarity": "epic", "name": "Sala", "page": False}]}]}
        (self.record / "latest" / "me.json").write_text(json.dumps(me))
        (self.record / "latest" / "catalog.json").write_text(json.dumps(catalog))

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_card_uses_the_exact_game_value(self):
        (self.live / "exact_values.json").write_text(json.dumps({"MAL-09": {"count": 0, "value": 91.0, "at": 5.0}}))
        it = build(self.record, self.live)["items"]["MAL-09"]
        self.assertEqual((it["value"], it["exact"], it["held"], it["held_value"]), (91.0, True, 0, None))

    def test_estimate_when_the_game_was_not_asked(self):
        it = build(self.record, self.live)["items"]["MAL-09"]
        self.assertEqual((it["value"], it["exact"]), (91.0, False))          # 70 x 1.3 x 1.0

    def test_exact_for_another_copy_count_is_ignored(self):
        (self.live / "exact_values.json").write_text(json.dumps({"MAL-02": {"count": 1, "value": 3.3, "at": 5.0}}))
        it = build(self.record, self.live)["items"]["MAL-02"]
        self.assertFalse(it["exact"])                                         # we hold 2 now, not 1
        self.assertEqual((it["held"], it["held_value"], it["spare_value"]), (2, 13.0, 3.3))

    def test_non_page_card_is_flagged(self):
        self.assertFalse(build(self.record, self.live)["items"]["MAL-11"]["page"])

    def test_missing_files_give_an_empty_answer(self):
        self.assertEqual(build(self.record / "nope", self.live)["items"], {})


if __name__ == "__main__":
    unittest.main()
