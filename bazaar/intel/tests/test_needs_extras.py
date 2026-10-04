"""Cards outside the pages (epics) must show up as opportunities and on the watch list (the LAV-11 case)."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.intel.needs import needs_report, summary_text


class NonPageOpportunity(unittest.TestCase):
    def test_epic_asked_below_value_only_in_the_feed(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "record"
            latest = rec / "latest"
            (latest / "books").mkdir(parents=True)
            (rec / "feed").mkdir()
            lav = [{"id": f"LAV-{i:02d}", "name": "c", "rarity": "common", "book": 10, "page": True, "hidden": False}
                   for i in range(1, 11)] + [{"id": "LAV-11", "name": "La Casa Encendida", "rarity": "epic", "book": 180,
                                              "page": False, "hidden": False}]
            docs = {"catalog": {"sets": [{"id": "LAV", "name": "Lavapiés", "released": True, "cards": lav}]},
                    "me": {"id": "t10", "cash": 55, "affinity": {"LAV": 1.6}, "assets": []},
                    "venues": {"venues": [{"venue": "rastro", "fee_bps": 500, "fee_per_card": 1}]},
                    "dealers": {"personas": []}, "leaderboard": {"tick": 518, "teams": []}, "clock": {"tick": 518}}
            for name, doc in docs.items():
                (latest / f"{name}.json").write_text(json.dumps(doc))
            (latest / "books" / "rastro.json").write_text(json.dumps({"venue": "rastro", "offers": []}))
            epic = {"id": 787, "kind": "card", "ref": "LAV-11", "rarity": "epic", "set": "LAV"}
            feed = [{"type": "pack.opened", "tick": 500, "payload": {"team": "t08", "pack": "sobre_plata", "best": epic}},
                    {"type": "offer.listed", "tick": 517, "actor": "t08", "payload": {"venue": "rastro", "offer": {
                        "id": 7716, "maker": "t08", "to": None, "venue": "rastro", "thread": None, "status": "open",
                        "give": {"cash": 0, "assets": [epic], "types": []}, "want": {"cash": 125, "assets": [], "types": []},
                        "expires_tick": 520}}}]
            (rec / "feed" / "2026-10-03.jsonl").write_text("\n".join(json.dumps(r) for r in feed) + "\n")
            rep = needs_report(rec, Path(d) / "live")
            o = [x for x in rep["opportunities"] if x.get("ref") == "LAV-11"]
            self.assertEqual(len(o), 1)
            self.assertEqual((o[0]["kind"], o[0]["offer"], o[0]["price"], o[0]["our_value"]),
                             ("buy_below_value", 7716, 125, 288.0))
            self.assertTrue(o[0]["non_page"])
            self.assertGreater(o[0]["cash_gap"], 0)
            self.assertEqual(rep["opportunities"][0]["ref"], "LAV-11")          # the biggest gain comes first
            w = rep["watch"][0]
            self.assertEqual((w["ref"], w["holder"], w["asks"][-1]["price"]), ("LAV-11", "t08", 125))
            self.assertIn("WATCH", summary_text(rep))


if __name__ == "__main__":
    unittest.main()
