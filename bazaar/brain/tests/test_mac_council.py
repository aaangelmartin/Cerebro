"""On the Mac the council votes three times independently while the hourly cap has room, else in one call."""
import unittest
from unittest import mock

from bazaar.brain import council, strategy as S
from bazaar.llm import cli_backend, client as real


class R:
    def __init__(self, inp, model="claude-cli"):
        self.tool_calls, self.text, self.model = [{"name": "x", "input": inp}], "", model


VOTE = {"verdict": "approve", "reason": "gain 8 P inside the goal cap", "rail_risk": False}


class MacCouncilTest(unittest.TestCase):
    def _patch(self, headroom, ask):
        return mock.patch.multiple(cli_backend, mode=lambda *a, **k: "auto", available=lambda *a, **k: True,
                                   headroom=lambda *a, **k: headroom, ask_cli=ask)

    def test_three_independent_calls_when_there_is_room(self):
        calls = []

        def ask(system, messages, tool, **kw):
            calls.append((system, kw.get("effort")))
            return R(dict(VOTE))
        with self._patch(40, ask):
            votes = S._mac_council(council, "brief", real)
        self.assertEqual(len(calls), len(S.COUNCIL_ROLES))
        self.assertEqual({v["role"] for v in votes}, set(S.COUNCIL_ROLES))
        self.assertEqual({e for _, e in calls}, {"low"})                       # votes stay quick
        self.assertEqual(len({s for s, _ in calls}), len(S.COUNCIL_ROLES))      # one system prompt per role

    def test_single_call_near_the_cap(self):
        calls = []

        def ask(system, messages, tool, **kw):
            calls.append(tool["name"])
            return R({"votes": [{**VOTE, "role": r} for r in S.COUNCIL_ROLES]})
        with self._patch(S.MAC_COUNCIL_ROOM - 1, ask):
            votes = S._mac_council(council, "brief", real)
        self.assertEqual(calls, [S.MAC_COUNCIL_TOOL_NAME])
        self.assertEqual(len(votes), len(S.COUNCIL_ROLES))

    def test_not_on_the_mac_for_an_injected_llm(self):
        with self._patch(40, lambda *a, **k: R(dict(VOTE))):
            self.assertIsNone(S._mac_council(council, "brief", object()))


if __name__ == "__main__":
    unittest.main()
