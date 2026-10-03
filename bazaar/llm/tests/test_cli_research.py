"""Deep research on the Mac: a read-only command line, a snapshot without secrets, weighted against the cap."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.llm import cli_backend as C


class FakeProc:
    def __init__(self, out, rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


class ResearchCommandTest(unittest.TestCase):
    def test_command_is_read_only(self):
        cmd = C.research_command()
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "Read,Grep,Glob")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(cmd[cmd.index("--permission-prompts") + 1], "none")
        self.assertEqual(cmd[cmd.index("--max-turns") + 1], "25")
        for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, cmd)
        joined = " ".join(cmd)
        for bad in ("dangerously", "Bash", "Edit", "Write", "WebFetch", "bypassPermissions"):
            self.assertNotIn(bad, joined.replace(C.RESEARCH_SYSTEM, ""))

    def test_snapshot_copies_named_files_only(self):
        with tempfile.TemporaryDirectory() as d:
            live, rec, docs = Path(d) / "live", Path(d) / "record", Path(d) / "docs"
            (rec / "latest").mkdir(parents=True); (rec / "feed").mkdir(); live.mkdir(); docs.mkdir()
            (live / "decisions.jsonl").write_text('{"tick":1}\n')
            (live / "broker.json").write_text('{"key":"SECRET"}')
            (live / "control.json").write_text("{}")
            (live / "llm_spend.json").write_text("{}")
            (rec / "latest" / "me.json").write_text("{}")
            (rec / "feed" / "2026-10-03.jsonl").write_text('{"id":1}\n')
            (docs / "rivales-analisis.md").write_text("# x")
            dest = C.research_snapshot(live, rec, docs, Path(d) / "snap")
            names = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
            self.assertEqual(names, ["docs/rivales-analisis.md", "live/decisions.jsonl",
                                     "record/feed/2026-10-03.jsonl", "record/latest/me.json"])
            self.assertFalse(any(p.is_symlink() for p in dest.rglob("*")))

    def test_run_counts_five_calls_and_returns_text(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            (live / "control.json").write_text(json.dumps({"brain_backend": "auto", "mac_calls_per_hour": 60}))
            seen = {}

            def runner(cmd, **kw):
                seen.update(cmd=cmd, kw=kw)
                return FakeProc(json.dumps({"result": "FINDINGS\n- x (live/a.jsonl:2)", "num_turns": 7,
                                            "total_cost_usd": 0.5, "is_error": False}))
            wd = Path(d) / "wd"; wd.mkdir()
            out = C.run_research("why did t12 jump?", live=live, runner=runner, workdir=wd)
            self.assertIn("FINDINGS", out["text"])
            self.assertEqual(out["turns"], 7)
            self.assertEqual(C.calls_last_hour(live), C.RESEARCH_WEIGHT)
            self.assertNotIn("ANTHROPIC_API_KEY", seen["kw"]["env"])
            self.assertEqual(seen["kw"]["cwd"], str(wd))
            self.assertIn("why did t12 jump?", seen["kw"]["input"])
            st = C.status(live)
            self.assertEqual(st["research_sessions"], 1)
            self.assertEqual(st["cli_cost_reported_total"], 0.5)

    def test_run_refused_near_the_cap_and_backs_off_on_limit(self):
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            (live / "control.json").write_text(json.dumps({"brain_backend": "auto", "mac_calls_per_hour": 6}))
            import time
            (live / "mac_backend.json").write_text(json.dumps({"calls": [time.time()] * 3}))
            with self.assertRaises(C.CLIError) as e:
                C.run_research("x", live=live, runner=lambda *a, **k: FakeProc("{}"), workdir=Path(d))
            self.assertEqual(e.exception.kind, "cap")
            (live / "mac_backend.json").write_text("{}")
            with self.assertRaises(C.CLIError) as e:
                C.run_research("x", live=live, workdir=Path(d),
                               runner=lambda *a, **k: FakeProc(json.dumps({"is_error": True, "result": ""}), 1,
                                                                 "Claude usage limit reached"))
            self.assertEqual(e.exception.kind, "limit")
            self.assertEqual(C.status(live)["state"], "backoff")

    def test_control_switch_and_slots(self):
        self.assertEqual(C.validate_control({"brain_deep_research": "off"}), {"brain_deep_research": False})
        self.assertEqual(C.validate_control({"brain_deep_research": True}), {"brain_deep_research": True})
        with self.assertRaises(ValueError):
            C.validate_control({"brain_deep_research": "maybe"})
        with tempfile.TemporaryDirectory() as d:
            live = Path(d)
            self.assertTrue(C.deep_research_on(live))
            r1 = C._acquire(live, 0.0, first=C.MAX_CONCURRENT - C.RESEARCH_SLOTS)
            r2 = C._acquire(live, 0.0, first=C.MAX_CONCURRENT - C.RESEARCH_SLOTS)      # two research sessions...
            with self.assertRaises(C.CLIError):
                C._acquire(live, 0.0, first=C.MAX_CONCURRENT - C.RESEARCH_SLOTS)      # ...and no third
            plan = C._acquire(live, 0.0)                               # a plan still finds its own slot
            with self.assertRaises(C.CLIError):
                C._acquire(live, 0.0)
            for x in (r1, r2, plan):
                x.close()
            self.assertEqual(C.DEFAULT_CALLS_PER_HOUR, 60)

    def test_plans_think_harder_than_votes(self):
        self.assertEqual(C.PLAN_EFFORT, "high")
        cmd = C.command("sys", None, C.PLAN_EFFORT)
        self.assertEqual(cmd[cmd.index("--effort") + 1], "high")


if __name__ == "__main__":
    unittest.main()
