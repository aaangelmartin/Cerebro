import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from bazaar import config
from bazaar.core.ledger import Ledger
from bazaar.llm import client
from bazaar.llm.router import KeyRouter, LLMTimeout, LLMUnavailable, cost_usd, madrid_day


class APIErr(Exception):
    def __init__(self, status, msg="err"):
        super().__init__(msg)
        self.status_code = status


class APITimeoutError(Exception):
    pass


def resp(text="ok", inp=100, out=10, cread=0, cwrite=0, tool=None):
    content = [NS(type="text", text=text)]
    if tool:
        content.append(NS(type="tool_use", id="tu1", name=tool, input={"x": 1}))
    return NS(content=content, stop_reason="end_turn",
              usage=NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cread,
                       cache_creation_input_tokens=cwrite))


class FakeSDK:
    """Per-key scripted behaviour: a list of responses/exceptions/callables consumed in order."""

    def __init__(self, scripts):
        self.scripts, self.calls, self.lock = scripts, [], threading.Lock()

    def factory(self, key):
        sdk = self

        class Messages:
            def create(self, **kw):
                with sdk.lock:
                    sdk.calls.append((key, kw))
                    step = sdk.scripts[key].pop(0) if sdk.scripts[key] else resp()
                if callable(step) and not isinstance(step, Exception):
                    step = step(kw)
                if isinstance(step, Exception):
                    raise step
                return step

        return NS(messages=Messages())


class Base(unittest.TestCase):
    keys = [("A", "ka"), ("B", "kb")]

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "llm_spend.json"
        self.router = KeyRouter(keys=self.keys, path=self.path, key_cap=100, day_cap=100, shares={"*": 1.0})
        client.set_router(self.router)
        self.lg = Ledger(self.dir.name)
        client.set_ledger(self.lg)
        client._clients.clear()

    def tearDown(self):
        client.set_router(None)
        client.set_ledger(None)
        client._clients.clear()
        self.dir.cleanup()

    def sdk(self, **scripts):
        keymap = dict(self.keys)
        f = FakeSDK({keymap[k]: list(v) for k, v in scripts.items()})
        p = mock.patch.object(client, "make_client", f.factory)
        p.start()
        self.addCleanup(p.stop)
        return f

    def ask(self, **kw):
        base = dict(purpose="duels", system="s", messages=[{"role": "user", "content": "hi"}])
        base.update(kw)
        return client.ask(**base)


class CostTest(unittest.TestCase):
    def test_cost_includes_cache(self):
        u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 1_000_000}
        self.assertAlmostEqual(cost_usd(config.OPUS, u), 4 + 20 + 0.4 + 5)
        self.assertAlmostEqual(cost_usd(config.HAIKU, {"input_tokens": 1_000_000}), 1.0)

    def test_madrid_day(self):
        from datetime import datetime, timezone
        ts = lambda *a: datetime(*a, tzinfo=timezone.utc).timestamp()
        self.assertEqual(madrid_day(ts(2026, 10, 4, 7, 0)), "sun")
        self.assertEqual(madrid_day(ts(2026, 10, 2, 21, 30)), "fri")     # 23:30 Madrid
        self.assertEqual(madrid_day(ts(2026, 10, 2, 22, 30)), "sat")     # 00:30 Madrid


class AskTest(Base):
    def test_basic_call_effort_cache_and_log(self):
        f = self.sdk(A=[resp("hello", cread=1000, tool="decide")], B=[])
        sys_blocks = client.cached_system("stable", "volatile")
        r = self.ask(system=sys_blocks, tools=[{"name": "decide", "input_schema": {"type": "object"}}])
        self.assertEqual((r.text, r.model, r.tool_calls[0]["name"]), ("hello", config.OPUS, "decide"))
        kw = f.calls[0][1]
        self.assertEqual(kw["output_config"], {"effort": "low"})
        self.assertEqual(kw["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", kw["system"][1])
        self.assertGreater(r.cost_usd, 0)
        rec = self.lg.tail("llm")[-1]
        self.assertEqual((rec["key"], rec["purpose"], rec["model"]), ("A", "duels", config.OPUS))
        self.assertNotIn("ka", json.dumps(rec))
        saved = json.loads(self.path.read_text())
        self.assertAlmostEqual(saved["keys"]["A"], r.cost_usd, places=6)
        self.assertEqual(client.spend_today()["calls"], 1)

    def test_no_effort_for_haiku(self):
        f = self.sdk(A=[resp()], B=[])
        self.ask(model=config.HAIKU)
        self.assertNotIn("output_config", f.calls[0][1])

    def test_forced_tool_choice_relaxed_for_opus_and_sonnet(self):
        f = self.sdk(A=[resp(), resp()], B=[])
        forced = {"type": "tool", "name": "decide"}
        self.ask(tool_choice=forced, tools=[{"name": "decide"}])
        self.ask(tool_choice=forced, tools=[{"name": "decide"}], model=config.HAIKU)
        self.assertEqual(f.calls[0][1]["tool_choice"], {"type": "auto"})
        self.assertEqual(f.calls[1][1]["tool_choice"], forced)

    def test_picks_key_with_most_budget_left(self):
        self.router.state["keys"] = {"A": 50.0, "B": 10.0}
        f = self.sdk(A=[], B=[resp()])
        self.assertEqual(self.ask().key, "B")
        self.assertEqual(f.calls[0][0], "kb")

    def test_dead_key_failover(self):
        f = self.sdk(A=[APIErr(401, "invalid x-api-key")], B=[resp()])
        self.assertEqual(self.ask().key, "B")
        self.assertIn("A", self.router.dead)
        self.ask()
        self.assertEqual([c[0] for c in f.calls], ["ka", "kb", "kb"])

    def test_credit_balance_kills_key(self):
        self.sdk(A=[APIErr(400, "Your credit balance is too low")], B=[resp()])
        self.ask()
        self.assertIn("A", self.router.dead)

    def test_overloaded_cools_and_retries_other(self):
        self.sdk(A=[APIErr(529, "Overloaded")], B=[resp()])
        self.assertEqual(self.ask().key, "B")
        self.assertGreater(self.router.cool["A"], time.time())

    def test_all_dead(self):
        self.sdk(A=[APIErr(403)], B=[APIErr(401)])
        with self.assertRaises(LLMUnavailable):
            self.ask()

    def test_fatal_bad_request(self):
        self.sdk(A=[APIErr(400, "messages: field required")], B=[])
        with self.assertRaises(LLMUnavailable):
            self.ask()
        self.assertEqual(self.router.dead, {})

    def test_deadline_timeout(self):
        self.sdk(A=[APITimeoutError("Request timed out.")], B=[])
        with self.assertRaises(LLMTimeout):
            self.ask(deadline=time.time() + 0.3)

    def test_timeout_param_follows_deadline(self):
        f = self.sdk(A=[resp()], B=[])
        self.ask(deadline=time.time() + 5)
        self.assertLessEqual(f.calls[0][1]["timeout"], 5)
        self.assertGreater(f.calls[0][1]["timeout"], 4)


class SingleKeyTest(Base):
    keys = [("A", "ka")]

    def test_waits_cooldown_then_same_key(self):
        with mock.patch.dict(client.COOLDOWN_S, {"overloaded": 0.2}):
            f = self.sdk(A=[APIErr(529, "overloaded"), resp("second")])
            r = self.ask(deadline=time.time() + 5)
        self.assertEqual(r.text, "second")
        self.assertEqual(len(f.calls), 2)

    def test_cooldown_past_deadline(self):
        f = self.sdk(A=[APIErr(429, "rate limited")])
        t0 = time.time()
        with self.assertRaises(LLMTimeout):
            self.ask(deadline=time.time() + 2)
        self.assertLess(time.time() - t0, 1.0)
        self.assertEqual(len(f.calls), 1)


class BudgetTest(Base):
    def test_degrade_at_80_percent(self):
        day = self.router.day()
        self.router.state["days"][day] = {"usd": 81.0}
        f = self.sdk(A=[resp(), resp()], B=[resp(), resp()])
        self.assertEqual(self.ask().model, config.SONNET)
        self.assertEqual(self.ask(model=config.OPUS).model, config.SONNET)
        self.assertEqual(self.ask(model=config.HAIKU).model, config.HAIKU)
        self.assertTrue(any(r.get("event") == "degraded" for r in self.lg.tail("llm")))
        self.assertEqual(client.spend_today()["model_now"], config.SONNET)

    def test_day_cap(self):
        self.router.state["days"][self.router.day()] = {"usd": 100.0}
        self.sdk(A=[], B=[])
        with self.assertRaises(LLMUnavailable):
            self.ask()

    def test_key_cap(self):
        self.router.state["keys"] = {"A": 100.0}
        f = self.sdk(A=[], B=[resp()])
        self.assertEqual(self.ask().key, "B")
        self.router.state["keys"]["B"] = 100.0
        self.router._save()                      # the router re-reads the shared file before deciding
        with self.assertRaises(LLMUnavailable):
            self.ask()
        self.assertEqual(len(f.calls), 1)

    def test_spend_persists_and_merges_processes(self):
        self.sdk(A=[resp(inp=1_000_000, out=0)], B=[])
        self.ask(model=config.HAIKU)
        other = KeyRouter(keys=self.keys, path=self.path)
        other.record("B", config.HAIKU, {"input_tokens": 1_000_000}, "broker_policy")
        self.router.record("A", config.HAIKU, {"input_tokens": 1_000_000}, "duels")
        saved = json.loads(self.path.read_text())
        day = saved["days"][self.router.day()]
        self.assertAlmostEqual(day["usd"], 3.0)
        self.assertAlmostEqual(day["by_purpose"]["broker_policy"], 1.0)
        self.assertAlmostEqual(saved["keys"]["A"], 2.0)


class EffectiveCapTest(unittest.TestCase):
    """Day cap = min(DAY_CAP_USD, (left on keys + spent today) x share), ladder Opus/Sonnet/Haiku/none."""

    SAT = 1791021600.0     # 2026-10-03 12:00 Madrid (Saturday)
    SUN = SAT + 86400

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "llm_spend.json"

    def tearDown(self):
        self.dir.cleanup()

    def router(self, clock, keys=(("A", "ka"),), **kw):
        return KeyRouter(keys=list(keys), path=self.path, key_cap=100, day_cap=100, clock=lambda: clock, **kw)

    def test_saturday_keeps_money_for_sunday(self):
        r = self.router(self.SAT)
        self.assertEqual(r.day(), "sat")
        self.assertAlmostEqual(r.effective_day_cap(), 55.0)
        # Spending today does not shrink today's cap (it is a share of what was left at the start of the day).
        r.record("A", config.HAIKU, {"input_tokens": 20_000_000}, "duels")       # 20 $
        self.assertAlmostEqual(r.effective_day_cap(), 55.0)
        sun = self.router(self.SUN)
        self.assertEqual(sun.day(), "sun")
        self.assertAlmostEqual(sun.effective_day_cap(), 80.0)
        self.assertAlmostEqual(self.router(self.SAT - 86400).effective_day_cap(), 8.0)    # Friday: 10 % of 80 left
        # With three keys the configured 100 $ day cap still applies.
        three = self.router(self.SUN, keys=(("A", "a"), ("B", "b"), ("C", "c")))
        self.assertAlmostEqual(three.effective_day_cap(), 100.0)

    def test_ladder_reaches_haiku_then_code_only(self):
        r = self.router(self.SAT)                 # cap 55
        cases = [(0.0, config.OPUS), (0.79 * 55, config.OPUS), (0.80 * 55, config.SONNET),
                 (0.91 * 55, config.SONNET), (0.92 * 55, config.HAIKU), (0.999 * 55, config.HAIKU)]
        for usd, want in cases:
            r.state = {"keys": {"A": usd}, "days": {"sat": {"usd": usd}}}
            r._save()
            self.assertEqual(r.resolve(None), want, usd)
            self.assertEqual(r.resolve(config.OPUS), want, usd)
        self.assertEqual(r.resolve(config.HAIKU), config.HAIKU)
        r.state = {"keys": {"A": 55.0}, "days": {"sat": {"usd": 55.0}}}
        r._save()
        with self.assertRaises(LLMUnavailable):
            r.resolve(None)
        self.assertEqual(r.model_now(), "none")

    def test_summary_and_day_spent_see_other_processes(self):
        api = self.router(self.SAT)
        bot = self.router(self.SAT)
        self.assertEqual(api.summary()["usd"], 0)
        bot.record("A", config.HAIKU, {"input_tokens": 3_000_000}, "duels")
        self.assertAlmostEqual(api.day_spent(), 3.0)
        s = api.summary()
        self.assertAlmostEqual(s["usd"], 3.0)
        self.assertAlmostEqual(s["cap"], 55.0)
        self.assertAlmostEqual(s["by_key"]["A"]["usd_total"], 3.0)


class RaceTest(Base):
    def test_first_valid_wins_and_loser_accounted(self):
        def factory(key):
            sdk = NS()

            class M:
                def create(self, **kw):
                    if kw["model"] == config.OPUS:
                        time.sleep(0.4)
                        return resp("opus")
                    return resp("sonnet")

            sdk.messages = M()
            return sdk

        with mock.patch.object(client, "make_client", factory):
            client._clients.clear()
            r = client.race(models=[config.OPUS, config.SONNET], purpose="council", system="s",
                            messages=[{"role": "user", "content": "x"}], deadline=time.time() + 3)
            self.assertEqual(r.text, "sonnet")
            time.sleep(0.6)
        self.assertEqual(client.spend_today()["calls"], 2)
        self.assertTrue(any(rec.get("abandoned") for rec in self.lg.tail("llm")))

    def test_invalid_answers_and_timeout(self):
        def factory(key):
            class M:
                def create(self, **kw):
                    if kw["model"] == config.OPUS:
                        time.sleep(1.5)
                    return resp("bad")
            return NS(messages=M())

        with mock.patch.object(client, "make_client", factory):
            with self.assertRaises(LLMTimeout):
                client.race(models=[config.OPUS, config.SONNET], valid=lambda r: r.text == "good", purpose="x",
                            system="s", messages=[{"role": "user", "content": "x"}], deadline=time.time() + 0.5)


if __name__ == "__main__":
    unittest.main()
