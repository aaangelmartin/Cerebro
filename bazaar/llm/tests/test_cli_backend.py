"""The Mac backend: the Claude Code CLI as a tool-less, JSON-only LLM for el cerebro. No real CLI call here."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from bazaar.llm import cli_backend as M
from bazaar.llm import client
from bazaar.llm.router import LLMUnavailable

TOOL = {"name": "team_strategy", "input_schema": {
    "type": "object", "required": ["situation", "priorities"],
    "properties": {"situation": {"type": "string"}, "priorities": {"type": "array"},
                   "mode": {"type": "string", "enum": ["a", "b"]}}}}
GOOD = {"situation": "4th, 28.9", "priorities": ["sell RET at 30"]}


class Proc:
    def __init__(self, doc=None, rc=0, stdout=None, stderr=""):
        self.returncode, self.stderr = rc, stderr
        self.stdout = stdout if stdout is not None else json.dumps(doc)


def ok_doc(data=GOOD, **kw):
    return {"is_error": False, "subtype": "success", "result": json.dumps(data), "structured_output": data,
            "total_cost_usd": 0.31, "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 20},
            "modelUsage": {"claude-opus-5-5": {}}, **kw}


class Base(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.calls = []
        self.logged = []
        p = mock.patch.object(client, "_log", self.logged.append)
        p.start()
        self.addCleanup(p.stop)

    def control(self, **kw):
        (self.live / "control.json").write_text(json.dumps(kw))

    def runner(self, *results):
        it = iter(results)

        def run(cmd, **kw):
            self.calls.append((cmd, kw))
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r
        return run

    def ask(self, run, **kw):
        return M.ask_cli("SYSTEM", [{"role": "user", "content": [{"type": "text", "text": "REF"},
                                                              {"type": "text", "text": "PICTURE"}]}],
                         TOOL, purpose="strategy", live=self.live, runner=run, **kw)


class AskCliTest(Base):
    def test_returns_the_structured_answer_as_a_tool_call_at_no_cost(self):
        res = self.ask(self.runner(Proc(ok_doc())))
        self.assertEqual(res.tool_calls, [{"id": "mac", "name": "team_strategy", "input": GOOD}])
        self.assertEqual((res.model, res.key, res.cost_usd), ("claude-cli", "MAC", 0.0))
        self.assertEqual(res.extra["cli_cost_reported"], 0.31)
        row = self.logged[-1]
        self.assertEqual((row["key"], row["cost_usd"], row["cli_cost_reported"], row["purpose"]),
                         ("MAC", 0.0, 0.31, "strategy"))

    def test_the_call_is_tool_less_isolated_and_has_no_api_keys(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_API_KEY_B": "k2",
                                              "ANTHROPIC_AUTH_TOKEN": "t", "ANTHROPIC_BASE_URL": "u",
                                              "CLAUDE_CODE_USE_BEDROCK": "1", "HOME": "/h"}):
            self.ask(self.runner(Proc(ok_doc())))
        cmd, kw = self.calls[0]
        self.assertIn("-p", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--json-schema"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--system-prompt") + 1], "SYSTEM")
        self.assertEqual(json.loads(cmd[cmd.index("--json-schema") + 1]), TOOL["input_schema"])
        env = kw["env"]
        self.assertEqual(env.get("HOME"), "/h")
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_B", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                  "CLAUDE_CODE_USE_BEDROCK"):
            self.assertNotIn(k, env)
        self.assertIn("REF", kw["input"])
        self.assertIn("PICTURE", kw["input"])
        self.assertIn("JSON object", kw["input"])
        self.assertNotIn("ClaudeHackathon", kw["cwd"])           # an empty temp dir, not the repo

    def test_json_in_the_text_is_accepted_when_there_is_no_structured_output(self):
        doc = ok_doc(structured_output=None, result="Here it is:\n```json\n" + json.dumps(GOOD) + "\n```")
        self.assertEqual(self.ask(self.runner(Proc(doc))).tool_calls[0]["input"], GOOD)

    def test_an_answer_that_misses_the_schema_is_invalid_and_two_in_a_row_back_off(self):
        bad = ok_doc({"situation": "x"})
        with self.assertRaises(M.CLIError) as e:
            self.ask(self.runner(Proc(bad)))
        self.assertEqual(e.exception.kind, "invalid")
        self.assertEqual(M.status(self.live)["state"], "off")       # control says nothing: mode api
        self.control(brain_backend="auto")
        self.assertEqual(M.status(self.live)["state"], "ok")
        with self.assertRaises(M.CLIError):
            self.ask(self.runner(Proc(ok_doc({"situation": "x", "priorities": [], "mode": "zzz"}))))
        self.assertEqual(M.status(self.live)["state"], "backoff")

    def test_a_usage_limit_backs_off_ten_minutes(self):
        self.control(brain_backend="auto")
        doc = {"is_error": True, "result": "Claude usage limit reached. Your limit will reset at 7pm."}
        with self.assertRaises(M.CLIError) as e:
            self.ask(self.runner(Proc(doc, rc=1)))
        self.assertEqual(e.exception.kind, "limit")
        st = M.status(self.live)
        self.assertEqual(st["state"], "backoff")
        self.assertAlmostEqual(st["backoff_until"] - time.time(), M.BACKOFF_LIMIT_S, delta=5)
        with self.assertRaises(M.CLIError):                         # no call is made while backing off
            self.ask(self.runner())
        self.assertEqual(len(self.calls), 1)

    def test_a_timeout_is_an_error_and_backs_off(self):
        self.control(brain_backend="auto")
        with self.assertRaises(M.CLIError) as e:
            self.ask(self.runner(subprocess.TimeoutExpired("claude", 150)))
        self.assertEqual(e.exception.kind, "timeout")
        self.assertEqual(M.status(self.live)["state"], "backoff")
        self.assertEqual(self.logged[-1]["error_kind"], "mac_timeout")

    def test_the_hourly_cap_stops_calls(self):
        self.control(brain_backend="mac", mac_calls_per_hour=2)
        run = self.runner(Proc(ok_doc()), Proc(ok_doc()))
        self.ask(run)
        self.ask(run)
        self.assertEqual(M.status(self.live)["state"], "cap")
        self.assertEqual(M.status(self.live)["calls_last_hour"], 2)
        with self.assertRaises(M.CLIError) as e:
            self.ask(self.runner())
        self.assertEqual(e.exception.kind, "cap")
        self.assertFalse(M.available(self.live))

    def test_only_one_call_at_a_time(self):
        lock = M._acquire(self.live, 0)
        try:
            with self.assertRaises(M.CLIError) as e:
                self.ask(self.runner(Proc(ok_doc())))
            self.assertEqual(e.exception.kind, "busy")
        finally:
            lock.close()
        self.ask(self.runner(Proc(ok_doc())))


class RouteTest(Base):
    def route(self, **kw):
        args = dict(purpose="strategy", system="S", messages=[{"role": "user", "content": "x"}], tools=[TOOL],
                    deadline=None, effort="medium", live=self.live)
        args.update(kw)
        return M.route(**args)

    def test_api_mode_and_per_tick_purposes_never_use_the_mac(self):
        with mock.patch.object(M, "ask_cli") as cli:
            self.assertIsNone(self.route())                               # no control: api
            self.control(brain_backend="auto")
            self.assertIsNone(self.route(purpose="duels"))
            self.assertIsNone(self.route(purpose="council"))               # the bot's own council stays on the API
            self.assertIsNone(self.route(tools=None))
            cli.assert_not_called()

    def test_auto_uses_the_mac_and_falls_back_to_the_api_on_failure(self):
        self.control(brain_backend="auto")
        with mock.patch.object(M, "ask_cli", return_value="RES") as cli:
            self.assertEqual(self.route(), "RES")
            self.assertEqual(self.route(purpose="council", mac=True), "RES")
            self.assertEqual(cli.call_count, 2)
        with mock.patch.object(M, "ask_cli", side_effect=M.CLIError("timeout", "x")) as cli:
            self.assertIsNone(self.route())
            self.assertEqual(cli.call_count, 1)

    def test_an_invalid_answer_is_asked_once_more_then_the_api(self):
        self.control(brain_backend="auto")
        with mock.patch.object(M, "ask_cli", side_effect=M.CLIError("invalid", "x")) as cli:
            self.assertIsNone(self.route())
            self.assertEqual(cli.call_count, 2)

    def test_mac_mode_never_spends_on_the_api(self):
        self.control(brain_backend="mac")
        with mock.patch.object(M, "ask_cli", side_effect=M.CLIError("limit", "x")):
            with self.assertRaises(LLMUnavailable):
                self.route()

    def test_control_validation(self):
        self.assertEqual(M.validate_control({"brain_backend": "auto", "mac_calls_per_hour": 12}),
                         {"brain_backend": "auto", "mac_calls_per_hour": 12})
        for bad in ({"brain_backend": "gpu"}, {"mac_calls_per_hour": 0}, {"mac_calls_per_hour": True}):
            with self.assertRaises(ValueError):
                M.validate_control(bad)


class BrainCouncilOnTheMacTest(Base):
    """The brain's three council votes go to the Mac in ONE call; a fake llm (tests, eval) never does."""

    def votes(self, *verdicts):
        from bazaar.brain import strategy as S
        return {"votes": [{"role": r, "verdict": v, "reason": "numbers ok"} for r, v in zip(S.COUNCIL_ROLES, verdicts)]}

    def test_one_mac_call_gives_the_three_votes(self):
        from bazaar.brain import strategy as S
        res = client.LLMResult("", [{"id": "mac", "name": S.MAC_COUNCIL_TOOL_NAME,
                                     "input": self.votes("approve", "approve", "reject")}],
                               "claude-cli", "MAC", {}, 0.0, 1.0)
        with mock.patch.object(M, "mode", return_value="auto"), mock.patch.object(M, "available", return_value=True), \
                mock.patch.object(M, "ask_cli", return_value=res) as cli, \
                mock.patch.object(client, "ask", side_effect=AssertionError("the API must not be asked")):
            out = S.council_vote({}, {"goal_buys": {"MAL-09": 88}}, {"clock": {"tick": 1}}, ["goal MAL-09 88"],
                                 llm=client)
        self.assertEqual(cli.call_count, 1)
        self.assertEqual((out["ok"], out["yes"], len(out["votes"])), (True, 2, 3))
        self.assertEqual({v["role"] for v in out["votes"]}, set(S.COUNCIL_ROLES))

    def test_a_failed_mac_call_falls_back_to_the_api_voters(self):
        from bazaar.brain import strategy as S
        vote = client.LLMResult("", [{"id": "1", "name": "vote", "input": {"verdict": "approve", "reason": "ok"}}],
                                "claude-opus-5-5", "A", {}, 0.05, 1.0)
        with mock.patch.object(M, "mode", return_value="auto"), mock.patch.object(M, "available", return_value=True), \
                mock.patch.object(M, "ask_cli", side_effect=M.CLIError("timeout", "x")), \
                mock.patch.object(client, "ask", return_value=vote) as api:
            out = S.council_vote({}, {}, {"clock": {}}, ["x"], llm=client)
        self.assertEqual(api.call_count, 3)
        self.assertTrue(out["ok"])

    def test_an_injected_llm_never_uses_the_mac(self):
        from bazaar.brain import strategy as S

        class Fake:
            n = 0

            def ask(self, **kw):
                Fake.n += 1
                return client.LLMResult("", [{"id": "1", "name": "vote", "input": {"verdict": "reject", "reason": "no"}}],
                                        "fake", "A", {}, 0.0, 0.1)
        with mock.patch.object(M, "mode", return_value="auto"), mock.patch.object(M, "available", return_value=True), \
                mock.patch.object(M, "ask_cli", side_effect=AssertionError("no Mac call for a fake llm")):
            out = S.council_vote({}, {}, {"clock": {}}, ["x"], llm=Fake())
        self.assertEqual((Fake.n, out["ok"]), (3, False))


if __name__ == "__main__":
    unittest.main()
