"""Rival dossiers: rotation over all teams, splitting a research answer into files, and what the picture loads."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar.strategist import rivals as RV

BOARD = {"teams": [{"team": f"t{i:02d}", "rank": r, "score": 30 - r, "negotiating": 15, "market": 10, "venue": f"v{i:02d}"}
                   for r, i in enumerate([12, 14, 18, 10, 5, 1, 13, 17, 2, 4, 8, 9, 3, 6, 7, 11, 15, 16], 1)]}
ANSWER = """Intro text that is ignored.
## t05
SUMMARY: collects Salamanca, holds MAL-09; offer SAL-10 for it.
SCORE: rank 5, negotiating 20.9 (record/latest/leaderboard.json)
FOR US: wants SAL-07 at 20 (offer 10569)
## t12 — leader
- SUMMARY: buys El Retiro below book from Carmen.
BOUGHT TODAY: RET-08 at 24 (feed 5012)
## t99
SUMMARY: not a team we asked for.
"""


class RivalsTest(unittest.TestCase):
    def test_relevance_puts_allies_mentions_and_neighbours_first(self):
        order = RV.relevance(BOARD, allies={"t05"}, mentioned={"t08"})
        self.assertEqual(order[:2], ["t05", "t08"])
        self.assertEqual(set(order[2:4]), {"t18", "t14"})         # ranks 3 and 2: the nearest to our rank 4
        self.assertEqual(len(order), 17)
        self.assertNotIn("t10", order)

    def test_rotation_covers_every_team_then_refreshes_the_oldest(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            seen, now = [], time.time()
            for _ in range(6):
                teams = RV.next_teams(live, BOARD, allies={"t05"}, now=now)
                self.assertEqual(len(teams), 3)
                seen += teams
                RV.save(live, "\n".join(f"## {t}\nSUMMARY: x {t}\nSCORE: 1" for t in teams), teams, now=now)
                now += 900
            self.assertEqual(len(set(seen)), 17)                    # all 17 rivals within six sessions
            again = RV.next_teams(live, BOARD, allies={"t05"}, now=now)
            top = RV.relevance(BOARD, {"t05"})[:6]
            self.assertTrue(set(again) <= set(top))                 # the relevant teams' stale dossiers come first

    def test_save_splits_sections_and_writes_the_index(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            done = RV.save(live, ANSWER, ["t05", "t12"], now=1000.0, tick=800)
            self.assertEqual(done, ["t05", "t12"])
            self.assertFalse((live / "rivals" / "t99.md").exists())
            text = (live / "rivals" / "t05.md").read_text()
            self.assertIn("tick 800", text)
            self.assertIn("MAL-09", text)
            idx = json.loads((live / "rivals" / "index.json").read_text())
            self.assertEqual(idx["t05"]["summary"], "collects Salamanca, holds MAL-09; offer SAL-10 for it.")
            self.assertEqual(idx["t12"]["summary"], "buys El Retiro below book from Carmen.")
            self.assertEqual(RV.save(live, "no sections here", ["t05"]), [])

    def test_picture_loads_relevant_dossiers_and_summaries_of_the_rest(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            self.assertEqual(RV.for_picture(live, BOARD), {})
            teams = ["t05", "t12", "t16", "t15", "t11", "t07", "t06"]
            RV.save(live, "\n".join(f"## {t}\nSUMMARY: s {t}\n" + "x" * 2000 for t in teams), teams)
            pic = RV.for_picture(live, BOARD, allies={"t05"}, mentioned={"t16"})
            self.assertEqual(len(pic["dossiers"]), RV.PICTURE_TEAMS)
            self.assertIn("t05", pic["dossiers"])
            self.assertIn("t16", pic["dossiers"])
            self.assertLessEqual(len(pic["dossiers"]["t05"]), RV.PICTURE_CHARS)
            self.assertEqual(pic["covered"], 7)
            self.assertEqual(len(pic["index"]), 2)
            self.assertTrue(all(v["summary"].startswith("s t") for v in pic["index"].values()))

    def test_brief_names_the_teams(self):
        b = RV.brief(["t05", "t12"], BOARD)
        self.assertIn("- t05: rank 5", b)
        self.assertIn("## tNN", b)


if __name__ == "__main__":
    unittest.main()
