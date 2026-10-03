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


class ClaudeEnvTest(unittest.TestCase):
    def test_strips_api_keys_and_provider_switches(self):
        env = {"HOME": "/Users/x", "PATH": "/bin", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_API_KEY_A": "a",
               "ANTHROPIC_API_KEY_B": "b", "ANTHROPIC_API_KEY_C": "c", "ANTHROPIC_AUTH_TOKEN": "t",
               "ANTHROPIC_BASE_URL": "http://x", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1",
               "BAZAAR_ALLOW_REAL": "1"}
        out = T.claude_env(env)
        self.assertEqual(out, {"HOME": "/Users/x", "PATH": "/bin", "BAZAAR_ALLOW_REAL": "1"})


class FakeSh:
    """Records git/test commands and answers like a happy repository."""

    def __init__(self, tests_ok=True, changed=("bazaar/intel/__init__.py",), on_origin=False, reject_push=0):
        self.calls, self.tests_ok, self.changed = [], tests_ok, list(changed)
        self.on_origin, self.reject_push = on_origin, reject_push      # reject_push: how many pushes origin refuses

    def __call__(self, args, cwd=None, timeout=300, check=False, env=None):
        self.calls.append(list(args))
        out, rc = "", 0
        if args[:2] == ["git", "worktree"] and args[2] == "add":
            Path(args[5]).mkdir(parents=True, exist_ok=True)
        if args[:3] == ["git", "diff", "--cached"]:
            out = "\n".join(self.changed)
        if args[:2] == ["git", "rev-parse"]:
            out = "abc1234" if "--short" in args else ("abc1234def5678" if "--verify" in args else "base")
        if args[:2] == ["git", "show"]:
            out = "\n".join(self.changed)
        if args[:2] == ["git", "log"]:
            out = "docs(intel): add a package docstring"
        if args[:3] == ["git", "branch", "--show-current"]:
            out = T.BRANCH
        if "unittest" in args and not self.tests_ok:
            rc, out = 1, "FAILED (failures=1)"
        if args[:3] == ["git", "merge-base", "--is-ancestor"]:
            rc = 0 if self.on_origin else 1
        if args[:2] == ["git", "push"] and self.reject_push > 0:
            self.reject_push -= 1
            return subprocess.CompletedProcess(args, 1, "", "! [rejected] (fetch first)")
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


class ForkModeTest(JobTest):
    def test_next_finish_done(self):
        sh = FakeSh(changed=["bazaar/broker/engine.py"])
        t = self.make(sh)
        job = t.next_job()
        self.assertEqual((job["id"], job["class"], job["why"]), (self.it["id"], "auto", "auto"))
        self.assertIsNone(t.next_job())                         # claimed: not handed out twice
        res = t.finish_job(job["id"], "abc1234")
        self.assertEqual(res["result"], "done")
        self.assertEqual(self.restarted, ["broker"])
        self.assertTrue(any(c[:3] == ["git", "push", "-q"] and c[-1].endswith(":refs/heads/" + T.BRANCH)
                            for c in sh.calls))
        self.assertEqual(self.box.get(job["id"])["status"], "done")

    def test_finish_skips_the_push_when_the_commit_is_already_on_origin(self):
        sh = FakeSh(changed=["bazaar/broker/engine.py"], on_origin=True)
        t = self.make(sh)
        job = t.next_job()
        res = t.finish_job(job["id"], "abc1234")
        self.assertEqual(res["result"], "done")
        self.assertFalse(any(c[:2] == ["git", "push"] for c in sh.calls))
        self.assertEqual(self.restarted, ["broker"])
        self.assertEqual(self.box.get(job["id"])["status"], "done")

    def test_finish_republishes_on_fresh_origin_when_the_push_is_rejected(self):
        sh = FakeSh(changed=["bazaar/broker/engine.py"], reject_push=1)
        t = self.make(sh)
        job = t.next_job()
        res = t.finish_job(job["id"], "abc1234")
        self.assertEqual(res["result"], "done")
        self.assertTrue(any(c[:2] == ["git", "cherry-pick"] for c in sh.calls))
        pushes = [c for c in sh.calls if c[:2] == ["git", "push"]]
        self.assertEqual(len(pushes), 2)
        self.assertTrue(all("--force" not in c and "-f" not in c and not any(a.startswith("+") for a in c)
                            for c in pushes))
        self.assertEqual(pushes[-1][-1], "HEAD:refs/heads/" + T.BRANCH)

    def test_finish_gives_up_without_forcing_when_origin_keeps_rejecting(self):
        sh = FakeSh(changed=["bazaar/broker/engine.py"], reject_push=5)
        t = self.make(sh)
        job = t.next_job()
        res = t.finish_job(job["id"], "abc1234")
        self.assertEqual(res["result"], "push_failed")
        self.assertEqual(self.restarted, [])

    def test_finish_with_red_tests_reverts_locally_and_reopens(self):
        sh = FakeSh(tests_ok=False)
        t = self.make(sh)
        job = t.next_job()
        res = t.finish_job(job["id"], "abc1234")
        self.assertEqual(res["result"], "failed")
        self.assertTrue(any(c[:2] == ["git", "revert"] for c in sh.calls))
        self.assertFalse(any(c[:2] == ["git", "push"] for c in sh.calls))
        self.assertEqual(self.box.get(job["id"])["status"], "open")

    def test_finish_touching_rails_without_accept_is_parked(self):
        sh = FakeSh(changed=["bazaar/core/rails.py"])
        t = self.make(sh)
        job = t.next_job()
        res = t.finish_job(job["id"], "abc1234")
        self.assertEqual(res["result"], "needs_accept")
        self.assertFalse(any(c[:2] == ["git", "push"] for c in sh.calls))

    def test_fail(self):
        t = self.make(FakeSh())
        job = t.next_job()
        t.fail_job(job["id"], "the request is wrong")
        got = self.box.get(job["id"])
        self.assertEqual(got["status"], "open")
        self.assertIn("the request is wrong", got["human_note"])


if __name__ == "__main__":
    unittest.main()
