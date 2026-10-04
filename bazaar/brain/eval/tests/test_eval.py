import json
import tempfile
import unittest
from pathlib import Path

from bazaar.brain.eval import replay, run, scenarios
from bazaar.brain.eval.replay import World

DAY = replay.DAY_FILE


def _w(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class ReplayTest(unittest.TestCase):
    """The world builder replays full documents, offer diffs and book snapshots up to a moment."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.rec, self.live = root / "record", root / "live"
        (self.rec / "latest").mkdir(parents=True)
        _w(self.rec / "clock" / DAY, [{"seq": 1, "ts": 100, "tick": 10, "data": {"tick": 10, "t_hours": 1.0}},
                                      {"seq": 2, "ts": 130, "tick": 11, "data": {"tick": 11, "t_hours": 1.01}}])
        _w(self.rec / "me" / DAY, [{"seq": 1, "ts": 100, "tick": 10, "data": {"id": "t10", "cash": 50}},
                                   {"seq": 2, "ts": 200, "tick": 13, "data": {"id": "t10", "cash": 9}}])
        _w(self.rec / "my_offers" / DAY, [
            {"seq": 1, "ts": 101, "tick": 10, "added": [{"id": 1, "maker": "t10", "status": "open"},
                                                       {"id": 2, "maker": "t10", "status": "open"}], "removed": []},
            {"seq": 2, "ts": 140, "tick": 11, "added": [], "removed": ["1"]}])
        _w(self.rec / "book_snapshots" / DAY, [{"seq": 1, "ts": 90, "tick": 9, "venue": "rastro",
                                                "offers": [{"id": 7, "maker": "mx"}]}])
        _w(self.rec / "books" / DAY, [{"seq": 1, "ts": 120, "tick": 10, "venue": "rastro",
                                       "added": [{"id": 8, "maker": "my"}], "removed": [7]}])
        _w(self.rec / "dealers" / DAY, [
            {"seq": 1, "ts": 95, "tick": 9, "kind": "dealers", "data": {"personas": [{"id": "abuela", "status": "active"}]}},
            {"seq": 2, "ts": 125, "tick": 10, "kind": "dealers", "data": {"personas": [
                {"id": "abuela", "status": "active"}, {"id": "pilar", "status": "announced"}]}}])
        _w(self.rec / "feed" / DAY, [{"seq": 1, "ts": 110, "type": "x"}, {"seq": 2, "ts": 300, "type": "y"}])
        _w(self.live / "decisions.jsonl", [{"ts": 105, "tick": 10}, {"ts": 400, "tick": 20}])

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_at_moment(self):
        w = World(self.rec, self.live)
        self.assertEqual(w.tick_ts(11), 150.0)
        out = Path(self.tmp.name) / "out"
        built = w.build(150.0, out, control={"avoid_buy_sets": []})
        latest = built["latest"]
        self.assertEqual(json.loads((latest / "me.json").read_text())["cash"], 50)
        self.assertEqual([o["id"] for o in json.loads((latest / "my_offers.json").read_text())["offers"]], [2])
        self.assertEqual([o["id"] for o in json.loads((latest / "books" / "rastro.json").read_text())["offers"]], [8])
        self.assertEqual({p["id"] for p in json.loads((latest / "dealers.json").read_text())["personas"]},
                         {"abuela", "pilar"})
        self.assertEqual(len((out / "feed" / DAY).read_text().splitlines()), 1)
        self.assertEqual(len((built["live"] / "decisions.jsonl").read_text().splitlines()), 1)
        self.assertEqual(json.loads((built["live"] / "control.json").read_text())["avoid_buy_sets"], [])


class ChecksTest(unittest.TestCase):
    """Scenario graders read plans the way the brain writes them."""

    def test_plan_graders(self):
        sc = {s.id: s for s in scenarios.SCENARIOS}
        ctx = {"pic": {"our_open_offer_ids": [3628], "research": {"our_offer_outliers": {"outliers": [
            {"offer": 3628, "kind": "bid", "card": "MAL-09"}]}}}, "text": "", "events": []}
        good = {"cancel_offers": [3628], "priorities": ["Free the 40 P locked in the outbid MAL-09 bid"]}
        self.assertTrue(all(ok for _, ok, _ in sc["cash_locked"].llm(good, ctx)))
        self.assertFalse(all(ok for _, ok, _ in sc["cash_locked"].llm({"priorities": ["buy more"]}, ctx)))
        self.assertTrue(all(ok for _, ok, _ in sc["team5_ret01"].llm({"accept_offers": ["4167"]}, {})))
        self.assertTrue(all(ok for _, ok, _ in sc["ret_no_score"].llm({"avoid_buy_sets": ["RET"]}, {})))
        self.assertFalse(all(ok for _, ok, _ in sc["mal_goals"].llm({"goal_buys": {"MAL-09": 95}}, {})))

    def test_table_and_failures(self):
        res = [{"id": "a", "title": "t", "tick": 1, "expect": "e", "det": [["x", True, ""], ["y", False, "d"]],
                "llm": [], "llm_status": "not run"}]
        self.assertIn("1/2 FAIL", run.table(res))
        self.assertEqual(run.failures(res), ["a [code] y (d)"])


REAL = Path(__file__).resolve().parents[3] / "data"


@unittest.skipUnless((REAL / "record" / "clock" / DAY).exists(), "no recorded Saturday data")
class RealDataTest(unittest.TestCase):
    """Every scenario builds its picture from the real recording without crashing (no API call)."""

    def test_deterministic_mode_runs(self):
        res = run.run(record=REAL / "record", live=REAL / "live")
        self.assertEqual(len(res), len(scenarios.SCENARIOS))
        for r in res:
            self.assertNotEqual(r["det"][0][0], "build picture", r["det"])


if __name__ == "__main__":
    unittest.main()
