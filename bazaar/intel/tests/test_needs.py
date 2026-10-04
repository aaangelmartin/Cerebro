import json
import tempfile
import unittest
from pathlib import Path

from bazaar.intel.needs import _CatalogValues, needs_report, summary_text


def card(ref, rarity="common", book=10, page=True):
    return {"id": ref, "name": ref, "rarity": rarity, "book": book, "page": page, "hidden": False}


def asset(aid, ref, rarity="common"):
    return {"id": aid, "kind": "card", "ref": ref, "rarity": rarity, "set": ref.split("-")[0]}


class NeedsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rec = Path(self.tmp.name) / "record"
        latest = rec / "latest"
        (latest / "books").mkdir(parents=True)
        (rec / "feed").mkdir()
        mal = [card(f"MAL-{i:02d}") for i in range(1, 9)] + [card("MAL-09", "rare", 70), card("MAL-10", "rare", 70),
                                                             card("MAL-11", "epic", 180, page=False)]
        ret = [card(f"RET-{i:02d}") for i in range(1, 11)]
        catalog = {"sets": [{"id": "MAL", "name": "Malasaña", "released": True, "cards": mal},
                            {"id": "RET", "name": "El Retiro", "released": True, "cards": ret}]}
        assets = [asset(i, f"MAL-{i:02d}") for i in range(1, 9)] + [asset(20, "MAL-02"), asset(30, "RET-01")]
        me = {"id": "t10", "cash": 50, "affinity": {"MAL": 1.3, "RET": 1.1}, "assets": assets, "unlocked": ["chato"]}
        venues = {"venues": [{"venue": "rastro", "fee_bps": 500, "fee_per_card": 1},
                             {"venue": "v02", "fee_bps": 0, "fee_per_card": 0}]}
        dealers = {"personas": [{"id": "chato", "status": "active", "enabled": True, "open_to_all": True,
                                 "menu": {"sells": [{"rarity": "rare", "sets": "released", "list_price": 77}]}}]}
        lb = {"tick": 50, "teams": [{"team": "t17", "name": "Team 17", "score": 20, "negotiating": 15, "market": 5,
                                     "album_filled": 25, "album_slots": 50, "pages_complete": 1},
                                    {"team": "t05", "name": "Team 5", "score": 22}]}
        books = {"rastro": {"venue": "rastro", "offers": [
            # t17 bids 70 for MAL-09 (anonymised maker in the book, named in the feed)
            {"id": 1, "maker": "mx1", "venue": "rastro", "status": "open", "give": {"cash": 70},
             "want": {"types": ["card:MAL-09"]}},
            # t05 bids 20 for MAL-02 (we hold a spare worth little)
            {"id": 2, "maker": "mx2", "venue": "rastro", "status": "open", "give": {"cash": 20},
             "want": {"types": ["card:MAL-02"]}}]},
                 "v02": {"venue": "v02", "offers": [
            # t05 sells MAL-10 at 60 on a 0 % venue: below our value
            {"id": 3, "maker": "mx2", "venue": "v02", "status": "open", "give": {"assets": [asset(99, "MAL-10", "rare")]},
             "want": {"cash": 60}}]}}
        for name, doc in [("catalog", catalog), ("me", me), ("venues", venues), ("dealers", dealers),
                          ("leaderboard", lb)]:
            (latest / f"{name}.json").write_text(json.dumps(doc))
        for v, doc in books.items():
            (latest / "books" / f"{v}.json").write_text(json.dumps(doc))
        feed = [{"type": "offer.listed", "actor": "t17", "payload": {"offer": {"id": 1, "maker": "t17"}}},
                {"type": "offer.listed", "actor": "t05", "payload": {"offer": {"id": 2, "maker": "t05"}}},
                {"type": "offer.listed", "actor": "t05", "payload": {"offer": {"id": 3, "maker": "t05"}}},
                {"type": "settlement", "payload": {"price": 22, "persona": "abuela", "items": [
                    {"kind": "card", "ref": "RET-06", "frm": "abuela", "to": "t17"}]}},
                {"type": "thread.opened", "payload": {"team": "t17", "with": "abuela", "topic": {"buy": {"card": "RET-07"}}}}]
        (rec / "feed" / "2026-10-03.jsonl").write_text("\n".join(json.dumps(r) for r in feed) + "\n")
        self.rep = needs_report(rec, Path(self.tmp.name) / "live", values=_CatalogValues(me, catalog))

    def tearDown(self):
        self.tmp.cleanup()

    def test_ours_page_and_spares(self):
        mal = self.rep["ours"]["sets"]["MAL"]
        self.assertEqual((mal["held"], mal["page"]), (8, 10))     # the epic MAL-11 is not a page card
        self.assertTrue(mal["completes_page"])
        self.assertIn("MAL-02", {s["ref"] for s in self.rep["ours"]["spares"]})
        m10 = next(m for m in mal["missing"] if m["ref"] == "MAL-10")
        self.assertEqual(m10["best_price"], 60)                   # the 0 % ask beats Chato's 77

    def _report(self, protected):
        live = Path(self.tmp.name) / "live"
        live.mkdir(exist_ok=True)
        (live / "control.json").write_text(json.dumps({"protected": protected}))
        rec = Path(self.tmp.name) / "record"
        me = json.loads((rec / "latest" / "me.json").read_text())
        catalog = json.loads((rec / "latest" / "catalog.json").read_text())
        return needs_report(rec, live, values=_CatalogValues(me, catalog))

    def test_spare_is_the_unprotected_copy(self):
        # MAL-02: assets 2 and 20. Unprotected: a spare is listed, as today
        self.assertIn(next(s for s in self.rep["ours"]["spares"] if s["ref"] == "MAL-02")["asset"], (2, 20))
        # either copy protected by id: the spare shown is the other one
        for kept, free in ((20, 2), (2, 20)):
            sp = next(s for s in self._report([kept])["ours"]["spares"] if s["ref"] == "MAL-02")
            self.assertEqual((sp["asset"], sp["copies"]), (free, 2))
        # protected by name: no sellable spare
        self.assertNotIn("MAL-02", {s["ref"] for s in self._report(["MAL-02"])["ours"]["spares"]})

    def test_makers_resolved_through_feed(self):
        self.assertEqual(self.rep["rivals"]["t17"]["hunting"]["MAL-09"]["bid"], 70)
        self.assertIn("RET-07", self.rep["rivals"]["t17"]["hunting"])
        self.assertEqual(self.rep["rivals"]["t17"]["bought"][0]["ref"], "RET-06")

    def test_opportunities(self):
        kinds = {(o["kind"], o.get("ref") or o.get("set")) for o in self.rep["opportunities"]}
        self.assertIn(("sell_to_bid", "MAL-02"), kinds)          # 20 P bid - fee > our spare value
        self.assertIn(("buy_below_value", "MAL-10"), kinds)      # 60 P < 91 P
        self.assertIn(("competition", "MAL-09"), kinds)
        self.assertIn(("avoid_set", "RET"), kinds)               # 1/10 held, affinity 1.1
        self.assertGreater(self.rep["opportunities"][0]["gain"], 0)

    def test_summary_fits(self):
        text = summary_text(self.rep, max_chars=600)
        self.assertLessEqual(len(text), 600)
        self.assertIn("OPPORTUNITIES", summary_text(self.rep))

    def test_missing_files_are_harmless(self):
        with tempfile.TemporaryDirectory() as d:
            rep = needs_report(Path(d) / "record", Path(d) / "live", values=_CatalogValues({}, {}))
            self.assertEqual(rep["opportunities"], [])


if __name__ == "__main__":
    unittest.main()
