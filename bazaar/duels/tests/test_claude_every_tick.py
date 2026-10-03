"""Claude decides every duel move; we never bid against ourselves; the code fallback says why it ran."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.duels.domain import DuelsDomain
from bazaar.duels.opponent import OpponentMemory
from bazaar.duels.policy import Move


def duel(deadline=40, our=110, rival=None, msgs=None, days=False):
    d = {"duel": 7, "session": 2, "status": "live", "role": "seller", "item": "X",
         "issues": ["price", "days"] if days else ["price"], "your_limit": 73, "rival": "Rival Verde",
         "deadline_tick": deadline, "decay_per_round": 0.06, "rounds": 0,
         "your_offer": {"id": 1, "price": our, "tick": 20, "days": 0} if our else None,
         "rival_offer": {"id": 2, "price": rival, "tick": 21, "days": 0} if rival else None,
         "messages": msgs if msgs is not None else (
             [{"tick": 20, "from": "you", "text": "", "price": our, "days": None}] if our else [])}
    if days:
        d.update(your_days_weight=2.0, days_meaning="each day is worth 2 to you")
    return d


class Dom(DuelsDomain):
    def __init__(self, answers, **kw):
        tmp = Path(tempfile.mkdtemp()) / "m.json"
        super().__init__(memory=OpponentMemory(tmp, autosave=False), llm=object(), **kw)
        self.answers, self.asked = list(answers), 0

    def _ask(self, llm, v, opp, base, ctx):
        self.asked += 1
        a = self.answers.pop(0) if self.answers else None
        if isinstance(a, Exception):
            raise a
        return a


def sit(tick, **kw):
    return SimpleNamespace(tick=tick, duels=[duel(**kw)])


CTX = SimpleNamespace(deadline=None, budget={}, control={}, llm_ok=True, ledger=None)
MOVED = [{"tick": 20, "from": "you", "text": "", "price": 110, "days": None},
         {"tick": 21, "from": "Rival Verde", "text": "", "price": 80, "days": None}]


class NeverBidAgainstOurselves(unittest.TestCase):
    def test_silent_rival_no_message_and_no_claude_call(self):
        d = Dom([Move("offer", price=100, text="100", source="opus")])
        for tick in range(21, 37):                             # rival says nothing; 3+ ticks left
            self.assertEqual(d.decide(sit(tick), CTX), [], tick)
            self.assertEqual(d.fallback(sit(tick), CTX), [], tick)
        self.assertEqual(d.asked, 0)

    def test_claude_offer_against_a_silent_rival_becomes_a_wait(self):
        d = Dom([Move("offer", price=100, text="100", source="opus")], llm_every=1)
        d._needs_llm = lambda v: True                          # even if Claude is asked and wants to concede
        self.assertEqual(d.decide(sit(25), CTX), [])

    def test_single_final_step_keeps_a_good_margin(self):
        d = Dom([], use_llm=False)
        acts = d.fallback(sit(38), CTX)                        # 2 ticks left, rival still silent
        self.assertEqual(len(acts), 1)
        price = acts[0].params["price"]
        self.assertGreater(price - 73, 3)                      # not a slide to the limit (73)
        self.assertLess(price, 110)
        sent = [{"tick": 20, "from": "you", "text": "", "price": 110, "days": None},
                {"tick": 38, "from": "you", "text": "", "price": price, "days": None}]
        d0 = duel(our=price, msgs=sent)
        d0["your_offer"]["tick"] = 38
        again = SimpleNamespace(tick=39, duels=[d0])
        self.assertEqual(d.fallback(again, CTX), [])           # the final step is sent once

    def test_duels_two_also_holds(self):
        d = Dom([], use_llm=False)
        self.assertEqual(d.fallback(SimpleNamespace(tick=25, duels=[duel(days=True)]), CTX), [])

    def test_rival_moved_claude_is_asked_every_tick(self):
        d = Dom([Move("offer", price=104, text="104", source="opus")])
        acts = d.decide(sit(22, rival=80, msgs=MOVED), CTX)
        self.assertEqual(d.asked, 1)
        self.assertEqual([a.source for a in acts], ["opus"])


class FallbackSaysWhy(unittest.TestCase):
    def test_opening_when_claude_fails(self):
        d = Dom([RuntimeError("boom")])
        acts = d.decide(sit(21, our=None), CTX)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].source, "fallback")
        self.assertIn("[fallback: Claude failed (RuntimeError)]", acts[0].reason)

    def test_rival_moved_and_claude_fails(self):
        d = Dom([RuntimeError("boom")])
        acts = d.decide(sit(22, rival=80, msgs=MOVED), CTX)
        self.assertEqual(len(acts), 1)
        self.assertIn("[fallback: Claude failed (RuntimeError)]", acts[0].reason)


if __name__ == "__main__":
    unittest.main()
