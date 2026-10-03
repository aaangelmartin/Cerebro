import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from bazaar.outbox import Outbox
from bazaar.taller import run as T


def item(**kw):
    base = {"id": "code-1", "kind": "code", "status": "open", "severity": "low", "title": "Add a docstring",
            "diagnosis": "missing docstring", "proposed_change": "add it", "patch_sketch": "", "updated": 100.0}
    return {**base, **kw}


class ClassificationTest(unittest.TestCase):
    def test_gated_by_severity_and_topic(self):
        self.assertFalse(T.is_gated(item()))
        self.assertTrue(T.is_gated(item(severity="critical")))
        self.assertTrue(T.is_gated(item(title="Never-lose rail lets a bad accept through")))
        self.assertTrue(T.is_gated(item(diagnosis="the key router keeps a dead key")))
        self.assertTrue(T.is_gated(item(patch_sketch="edit bazaar/core/executor.py")))
        self.assertFalse(T.is_gated(item(title="Broker probe sends prices outside the ask/bid range")))

    def test_touches_gated_and_services(self):
        self.assertEqual(T.touches_gated(["bazaar/core/rails.py", "bazaar/market/domain.py"]), ["bazaar/core/rails.py"])
        self.assertEqual(T.services_for(["bazaar/broker/engine.py", "bazaar/broker/tests/test_x.py"]), ["broker"])
        self.assertEqual(T.services_for(["bazaar/dashboard/app.js"]), [])
        self.assertEqual(T.services_for(["bazaar/market/domain.py"]), ["bot"])
        self.assertEqual(T.services_for(["bazaar/brain/strategy.py"]), ["strategist", "bot"])

    def test_eligibility_state_machine(self):
        self.assertEqual(T.eligible(item(), {}), "auto")
        self.assertIsNone(T.eligible(item(severity="critical"), {}))                     # gated: waits
        self.assertEqual(T.eligible(item(severity="critical", status="accepted"), {}), "accepted")
        self.assertIsNone(T.eligible(item(status="done"), {}))
        done = {"code-1": {"state": "failed", "at": 200.0}}
        self.assertIsNone(T.eligible(item(status="open", updated=150.0), done))           # no retry on its own
        self.assertIsNone(T.eligible(item(status="accepted", updated=200.2), done))       # taller's own note
        self.assertEqual(T.eligible(item(status="accepted", updated=300.0), done), "accepted")  # human re-accepted
        running = {"code-1": {"state": "running", "at": 200.0}}
        self.assertIsNone(T.eligible(item(status="accepted", updated=300.0), running, now=400.0))


class FakeSh:
    """Records git/test commands and answers like a happy repository."""

    def __init__(self, tests_ok=True, changed=("bazaar/intel/__init__.py",)):
        self.calls, self.tests_ok, self.changed = [], tests_ok, list(changed)

    def __call__(self, args, cwd=None, timeout=300, check=False, env=None):
        self.calls.append(list(args))
        out, rc = "", 0
        if args[:2] == ["git", "worktree"] and args[2] == "add":
            Path(args[5]).mkdir(parents=True, exist_ok=True)
        if args[:3] == ["git", "diff", "--cached"]:
            out = "\n".join(self.changed)
        if args[:2] == ["git", "rev-parse"]:
            out = "abc1234" if "--short" in args else "base"
        if args[:3] == ["git", "branch", "--show-current"]:
            out = T.BRANCH
        if "unittest" in args and not self.tests_ok:
            rc, out = 1, "FAILED (failures=1)"
        return subprocess.CompletedProcess(args, rc, out, "")


class JobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.box = Outbox(d / "outbox.jsonl")
        self.it = self.box.file_code("Add a docstring to bazaar/intel/__init__.py", ["no docstring"],
                                     "the package has no docstring", "add one", severity="low")
        self.restarted = []

        def claude(wt, prompt):
            (wt / ".taller_commit_msg").write_text("docs(intel): add a package docstring")
            return {"ok": True, "result": "done", "cost_usd": 0.1}

        self.claude = claude
        self.dirs = d

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, sh, watch_errors=()):
        return T.Taller(outbox=self.box, repo=self.dirs, work=self.dirs / "work", live=self.dirs / "live", sh=sh,
                        claude=self.claude, restart=lambda s: self.restarted.append(s) or True,
                        watch=lambda svcs, since: list(watch_errors))

    def test_happy_path_done(self):
        sh = FakeSh()
        t = self.make(sh)
        res = t.poll_once()
        self.assertEqual(res["result"], "done")
        got = self.box.get(self.it["id"])
        self.assertEqual(got["status"], "done")
        self.assertIn("abc1234", got["human_note"])
        self.assertTrue(any(c[:2] == ["git", "commit"] for c in sh.calls))
        self.assertTrue(any(c[:3] == ["git", "push", "-q"] and c[-1] == f"HEAD:{T.BRANCH}" for c in sh.calls))
        self.assertFalse(any(c[:2] == ["git", "push"] and "--force" in " ".join(c) for c in sh.calls))
        self.assertEqual(self.restarted, ["strategist"])
        steps = [json.loads(l)["step"] for l in (self.dirs / "live" / "taller.jsonl").read_text().splitlines()]
        for s in ("claimed", "worktree", "claude", "diff", "tests", "pushed", "restart", "done"):
            self.assertIn(s, steps)
        self.assertIsNone(t.poll_once())                       # done: not taken again
        self.assertFalse((self.dirs / "work" / "lock").exists())

    def test_failing_tests_do_not_push(self):
        sh = FakeSh(tests_ok=False)
        res = self.make(sh).poll_once()
        self.assertEqual(res["result"], "failed")
        self.assertFalse(any(c[:2] == ["git", "push"] for c in sh.calls))
        self.assertEqual(self.box.get(self.it["id"])["status"], "open")

    def test_gated_diff_waits_for_accept(self):
        sh = FakeSh(changed=["bazaar/core/rails.py"])
        res = self.make(sh).poll_once()
        self.assertEqual(res["result"], "needs_accept")
        self.assertFalse(any(c[:2] == ["git", "push"] for c in sh.calls))
        self.assertIn("Aceptar", self.box.get(self.it["id"])["human_note"])

    def test_errors_after_deploy_revert(self):
        sh = FakeSh()
        res = self.make(sh, watch_errors=["bot: Traceback"]).poll_once()
        self.assertEqual(res["result"], "reverted")
        self.assertTrue(any(c[:2] == ["git", "revert"] for c in sh.calls))
        self.assertEqual(self.box.get(self.it["id"])["status"], "rejected")

    def test_lock_blocks_a_second_job(self):
        t = self.make(FakeSh())
        self.assertTrue(t.acquire())
        self.assertIsNone(self.make(FakeSh()).poll_once())
        t.release()


if __name__ == "__main__":
    unittest.main()
