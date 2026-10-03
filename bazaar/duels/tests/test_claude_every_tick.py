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

    def test_short_finish_three_steps_then_silence(self):
        d = Dom([], use_llm=False)
        self.assertEqual(d.fallback(sit(36), CTX), [])         # 4 ticks left: still silent
        prices, msgs, our = [], [{"tick": 20, "from": "you", "text": "", "price": 110, "days": None}], 110
        for tick in (37, 38, 39):                              # 3, 2, 1 ticks left
            dd = duel(our=our, msgs=list(msgs))
            acts = d.decide(SimpleNamespace(tick=tick, duels=[dd]), CTX)
            self.assertEqual(len(acts), 1, tick)
            our = acts[0].params["price"]
            self.assertIn(str(our), acts[0].params["text"])
            prices.append(our)
            msgs.append({"tick": tick, "from": "you", "text": "", "price": our, "days": None})
            again = duel(our=our, msgs=list(msgs))
            self.assertEqual(d.fallback(SimpleNamespace(tick=tick, duels=[again]), CTX), [])   # one per tick
        self.assertEqual(prices, sorted(prices, reverse=True))
        self.assertEqual(len(set(prices)), 3)
        self.assertGreater(prices[-1], 73)                     # never at or past our limit
        self.assertEqual(d.asked, 0)

    def test_late_answer_is_used_next_tick(self):
        import concurrent.futures as cf
        d = Dom([])
        fut = cf.Future()
        d._pending[7] = (fut, (21, 1, (80, None)))
        fut.set_result(Move("offer", price=104, text="104", source="opus"))
        v = d._views(sit(22, rival=80, msgs=MOVED), CTX)[0]
        d._pending[7] = (fut, (21, len(v.rival_msgs()), v.rival_offer.key()))
        acts = d.decide(sit(22, rival=80, msgs=MOVED), CTX)
        self.assertEqual(d.asked, 0)                           # no new call: last tick's answer
        self.assertEqual([(a.source, a.params["price"]) for a in acts], [("opus", 104)])

    def test_duels_two_also_holds(self):
        d = Dom([], use_llm=False)
        self.assertEqual(d.fallback(SimpleNamespace(tick=25, duels=[duel(days=True)]), CTX), [])

    def test_rival_moved_claude_is_asked_every_tick(self):
        d = Dom([Move("offer", price=104, text="104", source="opus")])
        acts = d.decide(sit(22, rival=80, msgs=MOVED), CTX)
        self.assertEqual(d.asked, 1)
        self.assertEqual([a.source for a in acts], ["opus"])


class RivalRepeatsItsPrice(unittest.TestCase):
    def test_fallback_holds_when_rival_price_unchanged(self):
        msgs = [{"tick": 20, "from": "you", "text": "", "price": 110, "days": None},
                {"tick": 21, "from": "Rival Verde", "text": "", "price": 80, "days": None},
                {"tick": 22, "from": "you", "text": "", "price": 108, "days": None},
                {"tick": 23, "from": "Rival Verde", "text": "", "price": 80, "days": None}]
        d = Dom([], use_llm=False)
        acts = d.fallback(sit(24, our=108, rival=80, msgs=msgs), CTX)
        self.assertEqual([a for a in acts if a.kind == "duel_message"], [])

    def test_fallback_steps_after_a_rival_move(self):
        msgs = [{"tick": 20, "from": "you", "text": "", "price": 110, "days": None},
                {"tick": 21, "from": "Rival Verde", "text": "", "price": 80, "days": None},
                {"tick": 22, "from": "you", "text": "", "price": 108, "days": None},
                {"tick": 23, "from": "Rival Verde", "text": "", "price": 86, "days": None}]
        d = Dom([], use_llm=False)
        acts = d.fallback(sit(24, our=108, rival=86, msgs=msgs), CTX)
        for a in acts:
            if a.kind == "duel_message":
                self.assertGreaterEqual(a.params["price"], 108 - 3)     # at most half of the rival's 6 P move


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
