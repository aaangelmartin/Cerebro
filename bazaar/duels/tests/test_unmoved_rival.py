"""A rival that repeats its exact terms after our step gets no new step from Claude either (duel 2420)."""
import unittest
from types import SimpleNamespace

from bazaar.duels.policy import Move
from bazaar.duels.tests.test_claude_every_tick import CTX, Dom, sit

SAME = [{"tick": 20, "from": "you", "text": "", "price": 110, "days": None},
        {"tick": 21, "from": "Rival Verde", "text": "", "price": 80, "days": None},
        {"tick": 22, "from": "you", "text": "", "price": 108, "days": None},
        {"tick": 23, "from": "Rival Verde", "text": "", "price": 80, "days": None}]
MOVED = SAME[:3] + [{"tick": 23, "from": "Rival Verde", "text": "", "price": 86, "days": None}]


def dom(*answers):
    d = Dom(list(answers), llm_every=1)
    d._needs_llm = lambda v: True
    return d


def kinds(acts):
    return [a.kind for a in acts]


class ClaudeDoesNotFeedAnUnmovedRival(unittest.TestCase):
    def test_claude_step_becomes_a_wait_when_rival_repeated_its_price(self):
        d = dom(Move("offer", price=100, text="100", source="opus"))
        self.assertEqual(d.decide(sit(24, our=108, rival=80, msgs=SAME), CTX), [])

    def test_claude_may_step_once_the_rival_moves(self):
        d = dom(Move("offer", price=104, text="104", source="opus"))
        acts = d.decide(sit(24, our=108, rival=86, msgs=MOVED), CTX)
        self.assertEqual(kinds(acts), ["duel_message"])
        self.assertEqual(acts[0].params["price"], 104)

    def test_claude_may_still_accept_the_repeated_offer(self):
        d = dom(Move("accept", source="opus"))
        acts = d.decide(sit(24, our=108, rival=80, msgs=SAME), CTX)
        self.assertEqual(kinds(acts), ["duel_accept"])

    def test_last_ticks_are_left_to_the_finish(self):
        d = dom(Move("offer", price=90, text="90", source="opus"))
        acts = d.decide(sit(24, deadline=26, our=108, rival=80, msgs=SAME), CTX)   # 2 ticks left
        self.assertTrue(acts and acts[0].kind in ("duel_message", "duel_accept"))

    def test_duels_two_with_days_also_holds(self):
        msgs = [dict(m, days=0) for m in SAME]
        d = dom(Move("offer", price=100, days=0, text="100 P with delivery in 0 days", source="opus"))
        self.assertEqual(d.decide(sit(24, our=108, rival=80, msgs=msgs, days=True), CTX), [])

    def test_a_change_of_days_counts_as_a_move(self):
        msgs = [dict(m, days=0) for m in SAME]
        msgs[-1]["days"] = 5
        d = dom(Move("offer", price=104, days=5, text="104 P with delivery in 5 days", source="opus"))
        s = sit(24, our=108, rival=80, msgs=msgs, days=True)
        s.duels[0]["rival_offer"]["days"] = 5
        self.assertEqual(kinds(d.decide(s, CTX)), ["duel_message"])


if __name__ == "__main__":
    unittest.main()
