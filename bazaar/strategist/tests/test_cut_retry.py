import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.strategist import run as R
from bazaar.strategist.run import Strategist


class FakeLLM:
    def __init__(self, answers):
        self.answers, self.prompts, self.max_tokens = list(answers), [], []

    def ask(self, **kw):
        self.prompts.append((lambda c: "\n".join(b.get("text", "") for b in c) if isinstance(c, list) else c)(kw["messages"][0]["content"]))
        self.max_tokens.append(kw["max_tokens"])
        return self.answers.pop(0)


def _plan():
    return SimpleNamespace(stop="tool_use", text="", model="m", cost_usd=0.1,
                           tool_calls=[{"name": R.STRATEGY_TOOL["name"], "input": {"priorities": ["buy LAV-11 at 125"]}}])


def _cut():
    return SimpleNamespace(stop="max_tokens", text="", model="m", cost_usd=0.1, tool_calls=[])


class CutRetryTest(unittest.TestCase):
    def _strategist(self, d, llm):
        live, rec = Path(d) / "live", Path(d) / "record"
        live.mkdir(); rec.mkdir()
        return Strategist(live=live, record=rec, llm=llm)

    def test_a_cut_answer_is_asked_again_compact_and_used(self):
        with tempfile.TemporaryDirectory() as d:
            llm = FakeLLM([_cut(), _plan()])
            got = self._strategist(d, llm).ask({}, "scheduled")
            self.assertEqual(got["raw"]["priorities"], ["buy LAV-11 at 125"])
            self.assertEqual(len(llm.prompts), 2)
            self.assertIn("KEEP THE PLAN COMPACT", llm.prompts[0])
            self.assertIn("PREVIOUS ANSWER WAS CUT", llm.prompts[1])
            self.assertGreaterEqual(llm.max_tokens[0], 24000)

    def test_cut_twice_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            llm = FakeLLM([_cut(), _cut()])
            st = self._strategist(d, llm)
            self.assertIsNone(st.ask({}, "scheduled"))
            self.assertIn("twice", st.errors[-1]["error"])


if __name__ == "__main__":
    unittest.main()
