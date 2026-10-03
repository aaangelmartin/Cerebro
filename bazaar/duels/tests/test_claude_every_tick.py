"""Claude decides every duel move; the code schedule is the last resort and says why it ran."""
import unittest
from types import SimpleNamespace

from bazaar.duels.domain import DuelsDomain
from bazaar.duels.opponent import OpponentMemory
from bazaar.duels.policy import Move
import tempfile
from pathlib import Path


def duel(tick_deadline=40, rival_offer=None, our=110):
    return {"duel": 7, "session": 2, "status": "live", "role": "seller", "item": "X", "issues": ["price"],
            "your_limit": 73, "rival": "Rival Verde", "deadline_tick": tick_deadline, "decay_per_round": 0.06,
            "rounds": 0, "your_offer": {"id": 1, "price": our, "tick": 20, "days": 0} if our else None,
            "rival_offer": rival_offer, "messages": []}


class Dom(DuelsDomain):
    def __init__(self, answers, **kw):
        tmp = Path(tempfile.mkdtemp()) / "m.json"
        super().__init__(memory=OpponentMemory(tmp, autosave=False), llm=object(), **kw)
        self.answers = list(answers)
        self.asked = 0

    def _ask(self, llm, v, opp, base, ctx):
        self.asked += 1
        a = self.answers.pop(0) if self.answers else None
        if isinstance(a, Exception):
            raise a
        return a


def sit(tick, **kw):
    return SimpleNamespace(tick=tick, duels=[duel(**kw)])


CTX = SimpleNamespace(deadline=None, budget={}, control={}, llm_ok=True, ledger=None)


class EveryTickTest(unittest.TestCase):
    def test_claude_is_asked_every_tick_when_nothing_moved(self):
        d = Dom([Move("offer", price=108, text="a", source="opus"), Move("offer", price=107, text="b", source="opus")])
        a1 = d.decide(sit(21), CTX)
        a2 = d.decide(sit(22), CTX)
        self.assertEqual(d.asked, 2)
        self.assertEqual([a1[0].source, a2[0].source], ["opus", "opus"])

    def test_one_failure_holds_the_line_instead_of_conceding(self):
        d = Dom([Move("offer", price=108, text="a", source="opus"), RuntimeError("boom")])
        d.decide(sit(21), CTX)
        self.assertEqual(d.decide(sit(22), CTX), [])           # hold: no message on the code schedule

    def test_fallback_is_last_resort_and_says_why(self):
        d = Dom([RuntimeError("boom")])                        # Claude never set a line in this duel
        acts = d.decide(sit(21), CTX)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].source, "fallback")
        self.assertIn("[fallback: Claude failed (RuntimeError)]", acts[0].reason)

    def test_two_failures_in_a_row_use_the_fallback(self):
        d = Dom([Move("offer", price=108, text="a", source="opus"), RuntimeError("x"), RuntimeError("y")])
        d.decide(sit(21), CTX)
        self.assertEqual(d.decide(sit(22), CTX), [])
        acts = d.decide(sit(23), CTX)
        self.assertEqual(len(acts), 1)
        self.assertIn("[fallback:", acts[0].reason)

    def test_near_the_deadline_the_fallback_moves(self):
        d = Dom([Move("offer", price=108, text="a", source="opus"), RuntimeError("x")])
        d.decide(sit(21), CTX)
        acts = d.decide(sit(38), CTX)                          # 2 ticks left
        self.assertEqual(len(acts), 1)


if __name__ == "__main__":
    unittest.main()
