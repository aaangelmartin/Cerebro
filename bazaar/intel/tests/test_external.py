import json
import tempfile
import unittest
from pathlib import Path

from bazaar.intel import external as ex

TEAM5 = """[03/10/2026, 10:25:01] ~ Daniel Suárez: Team 10 is already posting on v10. Their first offer is RET-06 at 55 P, far above the ~24 a RET uncommon goes for, so it probably won't sell [L]. If you talk to them, mention that only filled trades count for both of us: they should price at market and remember offers last 30 min.
[03/10/2026, 10:25:11] ~ Daniel Suárez: Hey Team 10, quick one: we have bid 4167 on El Rastro for your RET-01 at 20 P, addressed to you (we can't buy on our own v10). Could you accept it in the next few minutes? It expires around tick 290."""

TEAM12 = """03/10/26, 08:58 - Lucía (Team 12): ☀️ Good morning traders, ready for day 2?
We looked at yesterday's game:
💸 Teams paid at least 125 P in fees on El Rastro.
So we created a new market version built for that:
El Duende (v02): 0% fee, 0 P per card. Zero. Nada.
🤖 Just tell your agent:
"Each tick, read GET /api/venues/v02/offers. Post bids and asks with venue: "v02" and expires_in_ticks: 120."
Keep your primas. Finish your pages. 🃏"""


def _dirs():
    root = Path(tempfile.mkdtemp())
    live, rec = root / "live", root / "record"
    (rec / "latest").mkdir(parents=True)
    live.mkdir()
    (rec / "latest" / "venues.json").write_text(json.dumps({"venues": [
        {"venue": "v02", "owner": "t12"}, {"venue": "v07", "owner": "t10"}, {"venue": "v10", "owner": "t05"},
        {"venue": "rastro", "owner": "world"}]}))
    return live, rec


class ParseTest(unittest.TestCase):
    def test_ios_export_two_messages(self):
        msgs = ex.parse(TEAM5)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["author"], "Daniel Suárez")
        self.assertEqual(msgs[1]["ts"] - msgs[0]["ts"], 10)

    def test_android_multiline(self):
        msgs = ex.parse(TEAM12)
        self.assertEqual(len(msgs), 1)
        self.assertIn("El Duende (v02)", msgs[0]["text"])
        self.assertEqual(msgs[0]["author"], "Lucía (Team 12)")

    def test_headerless_paste_is_one_message(self):
        msgs = ex.parse("line one\nline two", by="angel", now=1000.0)
        self.assertEqual(msgs, [{"ts": 1000.0, "author": "angel", "text": "line one\nline two"}])


class IngestTest(unittest.TestCase):
    def test_team5_request_is_actionable_and_attributed(self):
        live, rec = _dirs()
        out = ex.ingest(TEAM5, by="angel", live_dir=live, record_dir=rec)
        a, b = out["added"]
        self.assertEqual(b["team"], "t05")                   # "our own v10"
        self.assertEqual(a["team"], "t05")                   # same author, learned from the second message
        self.assertEqual(b["entities"]["offer_ids"], [4167])
        self.assertEqual(b["entities"]["cards"], ["RET-01"])
        self.assertEqual(b["entities"]["ticks"], [290])
        self.assertIn(20.0, b["entities"]["prices"])
        self.assertTrue(b["actionable"])
        self.assertIn("request", b["types"])
        self.assertIn("Team 5: bid 4167 RET-01 20 P addressed to us", b["action_hint"])
        self.assertIn("complaint", a["types"])
        self.assertTrue(a["actionable"])

    def test_team12_promo(self):
        live, rec = _dirs()
        r = ex.ingest(TEAM12, by="angel", live_dir=live, record_dir=rec)["added"][0]
        self.assertEqual(r["team"], "t12")
        self.assertIn("promo", r["types"])
        self.assertIn("v02", r["entities"]["venues"])
        self.assertFalse(r["actionable"])

    def test_dedupe_and_digest(self):
        live, rec = _dirs()
        ex.ingest(TEAM5, by="angel", live_dir=live, record_dir=rec)
        again = ex.ingest(TEAM5, by="angel", live_dir=live, record_dir=rec)
        self.assertEqual(again["added"], [])
        self.assertEqual(again["duplicates"], 2)
        ts = ex.load(live)[0]["ts"]
        d = ex.recent_digest(live_dir=live, now=ts + 60)
        self.assertTrue(d.startswith("EXTERNAL MESSAGES"))
        self.assertIn("Actionable:", d)
        self.assertIn("<untrusted>", d)
        self.assertLessEqual(len(ex.recent_digest(max_chars=300, live_dir=live, now=ts + 60)), 300)


if __name__ == "__main__":
    unittest.main()
