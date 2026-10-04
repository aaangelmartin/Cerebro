import json
import tempfile
import unittest
from pathlib import Path

from bazaar.broker import policy_overlay as ov
from bazaar.broker.engine import BenchEngine, merge_policy


class OverlayTest(unittest.TestCase):
    def test_validate_bounds_and_unknown(self):
        clean, rej = ov.validate({"cross_rule": "quotes", "max_probes": 9, "wait_ticks": 1,
                                  "profiles": {"normal": {"wait_ticks": 1.5, "hazard": 2.0}, "evil": {}}})
        self.assertEqual(clean, {"cross_rule": "quotes", "profiles": {"normal": {"wait_ticks": 1.5}}})
        self.assertIn("max_probes=9", rej)
        self.assertTrue(any("unknown knob wait_ticks" in r for r in rej))
        self.assertTrue(any("profiles.normal.hazard" in r for r in rej))
        self.assertTrue(any(r.startswith("profiles.evil") for r in rej))

    def test_write_load_apply(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broker_policy.json"
            doc = ov.write(p, {"profiles": {"hard": {"endgame_ticks": 4}}, "bogus": 1}, by="cerebro", why="test")
            self.assertEqual(doc["rejected"], ["unknown knob bogus"])
            got = ov.load(p)
            self.assertEqual(got["version"], doc["version"])
            base = merge_policy(None)
            pol = ov.apply(base, got["policy"])
            self.assertEqual(pol["profiles"]["hard"]["endgame_ticks"], 4)
            self.assertEqual(base["profiles"]["hard"]["endgame_ticks"], merge_policy(None)["profiles"]["hard"]["endgame_ticks"])
            self.assertEqual(ov.load(Path(d) / "missing.json")["policy"], {})

    def test_engine_apply_policy_resets_rule(self):
        eng = BenchEngine({"cross_rule": "probe"})
        eng.probe_refusals = 2
        eng.apply_policy(merge_policy({"cross_rule": "quotes"}))
        self.assertEqual((eng.rule, eng.learn_rule, eng.probe_refusals), ("quotes", False, 0))


if __name__ == "__main__":
    unittest.main()


class OverlayInLoopTest(unittest.TestCase):
    def test_overlay_read_only_between_sessions_and_logged(self):
        from bazaar.broker import run, sim_book
        with tempfile.TemporaryDirectory() as d:
            ovf = Path(d) / "broker_policy.json"
            ov.write(ovf, {"profiles": {"normal": {"wait_ticks": 1.0}}}, by="cerebro", why="t")
            client = sim_book.SimClient(seed=3, sessions=2, gap_ticks=4)
            loop = run.BrokerLoop(client, Path(d) / "bench", merge_policy(None))
            first_start = client.sessions[0][0]
            for _ in range(first_start + 2):          # into the first session
                loop.poll(); client.advance()
            v1 = loop.overlay["version"]
            self.assertEqual(loop.engine.policy["profiles"]["normal"]["wait_ticks"], 1.0)
            ov.write(ovf, {"profiles": {"normal": {"wait_ticks": 3.0}}}, by="cerebro", why="t2")
            loop.poll(); client.advance()             # mid-session: unchanged
            self.assertEqual(loop.engine.policy["profiles"]["normal"]["wait_ticks"], 1.0)
            while client.tick < client.end_tick:
                loop.poll(); client.advance()
            self.assertEqual(loop.engine.policy["profiles"]["normal"]["wait_ticks"], 3.0)
            starts = []
            for f in (Path(d) / "bench").glob("*.jsonl"):
                starts += [json.loads(l) for l in f.read_text().splitlines() if '"type": "start"' in l]
            versions = [s.get("policy_version") for s in starts]
            self.assertIn(v1, versions)
            self.assertEqual(len(set(versions)), 2)
