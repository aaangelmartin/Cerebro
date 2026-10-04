"""The three-day table: each round is recovered from the published table marks."""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "global_leaderboard", Path(__file__).resolve().parents[2] / "tools" / "global_leaderboard.py")
glb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(glb)


def cut(tick, phases, marks):
    """marks: {team: (negotiating, market)} as the table would publish them."""
    return {"ts": 1000.0 + tick, "tick": tick,
            "phase": dict(phases), "weight": {1: 0.5, 2: 1.0, 3: 1.0},
            "teams": {t: {"team": t, "name": t, "negotiating": n, "market": m, "score": n + m} for t, (n, m) in marks.items()}}


def table(r1, r2, r3, p3):
    return (0.5 * r1 + r2 + p3 * r3) / (1.5 + p3)


class GlobalLeaderboardTest(unittest.TestCase):
    def test_each_round_comes_back_from_the_table(self):
        r = {"t10": {"neg": (20.0, 30.0, 10.0), "mkt": (0.0, 15.0, 11.25)},
             "t12": {"neg": (28.0, 20.0, 24.0), "mkt": (0.0, 18.0, 10.0)}}
        rows = [
            cut(100, {1: 1.0, 2: 0.0}, {t: (v["neg"][0], v["mkt"][0]) for t, v in r.items()}),
            cut(900, {1: 1.0, 2: 1.0}, {t: (table(v["neg"][0], v["neg"][1], 0, 0), table(v["mkt"][0], v["mkt"][1], 0, 0)) for t, v in r.items()}),
            cut(1000, {1: 1.0, 2: 1.0, 3: 0.1}, {t: (table(v["neg"][0], v["neg"][1], 0, 0.1), table(v["mkt"][0], v["mkt"][1], 0, 0.1)) for t, v in r.items()}),
            cut(1500, {1: 1.0, 2: 1.0, 3: 0.5}, {t: (table(*v["neg"], 0.5), table(*v["mkt"], 0.5)) for t, v in r.items()}),
        ]
        doc = glb.build(rows)
        us = next(t for t in doc["teams"] if t["team"] == "t10")
        self.assertAlmostEqual(us["r1"], 20.0, places=6)
        self.assertAlmostEqual(us["r2"], 45.0, places=6)
        self.assertAlmostEqual(us["negotiating"]["r3"], 10.0, places=6)
        self.assertAlmostEqual(us["market"]["r3"], 11.25, places=6)
        # the table once Sunday counts in full
        self.assertAlmostEqual(us["final"], (0.5 * 20 + 45 + 21.25) / 2.5, places=6)
        self.assertEqual([t["team"] for t in doc["teams"]], ["t12", "t10"])      # by the projected final
        self.assertEqual(doc["teams"][0]["rank_final"], 1)
        self.assertEqual(us["rank_r2"], 1)

    def test_no_cuts_is_an_empty_table(self):
        self.assertEqual(glb.build([])["teams"], [])

    def test_the_markdown_marks_us(self):
        rows = [cut(100, {1: 1.0, 2: 0.0}, {"t10": (20.0, 0.0)}),
                cut(1000, {1: 1.0, 2: 1.0, 3: 0.1}, {"t10": (25.0, 12.0)}),
                cut(1500, {1: 1.0, 2: 1.0, 3: 0.5}, {"t10": (22.0, 12.0)})]
        self.assertIn("**t10**", glb.markdown(glb.build(rows)))


if __name__ == "__main__":
    unittest.main()
