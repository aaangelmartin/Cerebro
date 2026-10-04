import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bazaar.broker import sim_book
from bazaar.core.types import Lesson
from bazaar.lab import broker_learn, gate
from bazaar.lab.run import Lab


def _session(bench: Path, run: str, eff: float, stall: float, version: str = "v0") -> None:
    bench.mkdir(parents=True, exist_ok=True)
    (bench / f"2026-10-03-{run}.jsonl").write_text(json.dumps({"type": "start", "policy_version": version}) + "\n")
    with open(bench / "results.jsonl", "a") as f:
        f.write(json.dumps({"type": "result", "run": run, "session": f"2026-10-03-{run}", "tick": 218,
                            "score": {"bench_efficiency": eff, "bench_points": 0.5}, "stall_efficiency": stall,
                            "stats": {"matches": 5, "refused": 0, "profile": "auto"}}) + "\n")


class SessionsTest(unittest.TestCase):
    def test_rows_carry_efficiency_vs_stall_and_policy_version(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            _session(live / "bench", "b7", 0.899, 0.892, "abc")
            _session(live / "bench", "b25", 0.933, 0.931)
            rows = broker_learn.sessions(live)
            self.assertEqual([r["run"] for r in rows], ["b7", "b25"])
            self.assertEqual(rows[0]["vs_stall"], 0.007)
            self.assertEqual(rows[0]["policy_version"], "abc")

    def test_no_bench_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(broker_learn.sessions(Path(d)), [])


class CandidateTest(unittest.TestCase):
    def _fake_eval(self, wins: bool):
        def ev(policy, seeds=0):
            better = wins and policy["profiles"]["normal"].get("wait_ticks") == 0.0
            x = 0.92 if better else 0.90
            return {"normal": x, "hard": x, "real": x, "normal_stall": 0.9, "hard_stall": 0.9, "real_stall": 0.9}
        return ev

    def test_clear_winner_is_proposed(self):
        grid = [{"profiles": {"normal": {"wait_ticks": 0.0}}}, {"profiles": {"normal": {"wait_ticks": 3.0}}}]
        with mock.patch.object(broker_learn, "evaluate", self._fake_eval(True)):
            best = broker_learn.best_candidate(broker_learn.load_policy(), {}, 5, grid)
        self.assertEqual(best["knob"], {"profiles": {"normal": {"wait_ticks": 0.0}}})
        self.assertAlmostEqual(best["delta"], 0.02)

    def test_no_clear_winner_no_proposal(self):
        grid = [{"profiles": {"normal": {"wait_ticks": 0.0}}}]
        with mock.patch.object(broker_learn, "evaluate", self._fake_eval(False)):
            self.assertIsNone(broker_learn.best_candidate(broker_learn.load_policy(), {}, 5, grid))

    def test_out_of_bounds_candidate_is_skipped(self):
        with mock.patch.object(broker_learn, "evaluate", self._fake_eval(True)):
            self.assertIsNone(broker_learn.best_candidate(broker_learn.load_policy(), {}, 5,
                                                          [{"profiles": {"normal": {"wait_ticks": 99}}}]))


class LabHookTest(unittest.TestCase):
    def _lab(self, d):
        lab_dir, live = Path(d) / "lab", Path(d) / "live"
        lab_dir.mkdir(); live.mkdir()
        return Lab(lab=lab_dir, live=live, use_llm=False), live

    def test_never_while_a_session_runs(self):
        with tempfile.TemporaryDirectory() as d:
            lab, live = self._lab(d)
            _session(live / "bench", "b7", 0.899, 0.892)
            (live / "broker_status.json").write_text(json.dumps({"active_runs": ["b25"], "session": "x"}))
            with mock.patch.object(broker_learn, "learn") as learn:
                self.assertIsNone(lab.learn_broker())
                learn.assert_not_called()

    def test_new_session_proposes_a_broker_lesson_once(self):
        with tempfile.TemporaryDirectory() as d:
            lab, live = self._lab(d)
            _session(live / "bench", "b7", 0.899, 0.892)
            (live / "broker_status.json").write_text(json.dumps({"active_runs": [], "session": None}))
            best = {"overlay": {"profiles": {"normal": {"wait_ticks": 0.0}}},
                    "knob": {"profiles": {"normal": {"wait_ticks": 0.0}}}, "delta": 0.01,
                    "deltas": {"normal": 0.01, "hard": 0.01, "real": 0.01}, "sim": {}, "current": {}}
            with mock.patch.object(broker_learn, "best_candidate", return_value=best):
                out = lab.learn_broker()
            self.assertTrue(out["new"])
            l = lab.store.get(out["lesson"])
            self.assertEqual((l.scope, l.status, l.created_by), ("broker", "shadow", "lab"))
            self.assertEqual(l.params["broker_policy"], best["overlay"])
            self.assertIsNone(lab.learn_broker())                      # rate limit: not again right away
            lab._broker_learn_at = 0.0
            with mock.patch.object(broker_learn, "best_candidate") as bc:
                self.assertFalse(lab.learn_broker()["new"])            # same sessions: nothing to learn
                bc.assert_not_called()

    def test_gate_leaves_broker_policy_proposals_to_the_brain(self):
        with tempfile.TemporaryDirectory() as d:
            lab, _ = self._lab(d)
            lab.store.upsert(Lesson(id="BRabc123", scope="broker", rule="Broker policy x beats the policy in use.",
                                    status="shadow", created_by="lab", params={"broker_policy": {"max_probes": 0}}))
            moves = gate.step(lab.store, lab.corpus, run_sim=False)
            self.assertFalse([m for m in moves if m.get("id") == "BRabc123"])
            self.assertEqual(lab.store.get("BRabc123").status, "shadow")


class RealProfileTest(unittest.TestCase):
    def test_refit_profile_matches_the_recorded_sessions(self):
        """Real sessions: stall 0.892 (b7) and 0.931 (b25), 8-10 of 20 traders matched."""
        effs, matched = [], []
        for seed in range(80):
            s = sim_book.SimSession.generate(seed, sim_book.REAL)
            if s.max_gain() <= 0:
                continue
            effs.append(sim_book.play(s, sim_book.stall_planner()))
            matched.append(sum(t.matched for t in s.traders))
        self.assertAlmostEqual(sum(effs) / len(effs), 0.915, delta=0.03)
        self.assertTrue(7.5 <= sum(matched) / len(matched) <= 11)


if __name__ == "__main__":
    unittest.main()
