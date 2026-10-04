"""A thread a human writes in from the dashboard (control.manual_threads) is not the bot's: it never
answers, accepts or closes it, and it opens no second thread with that dealer."""
from __future__ import annotations

import unittest

from bazaar.dealers.tests import test_card_switch as S
from bazaar.dealers.tests import test_domain as T

SIT, CTX = T.AuditFixes().sit, T.AuditFixes().ctx


def acts(control, th, tick=5):
    ctx = CTX(tick)
    ctx.control = control
    return T.domain().fallback(SIT(tick=tick, threads=[th]), ctx)


class ManualThreads(unittest.TestCase):
    def test_the_bot_moves_in_its_own_thread(self):
        th = S.thread([("d", 2, 27, S.CARD), ("u", 3, 12), ("d", 4, 26, S.CARD)])
        self.assertTrue([a for a in acts({}, th) if a.params.get("thread") == 10 or a.kind == "accept_offer"])

    def test_the_bot_leaves_a_manual_thread_alone(self):
        th = S.thread([("d", 2, 27, S.CARD), ("u", 3, 12), ("d", 4, 26, S.CARD)])
        out = acts({"manual_threads": [10]}, th)
        self.assertEqual([a for a in out if a.kind in ("thread_message", "close_thread", "accept_offer")], [])
        self.assertEqual([a for a in out if a.kind == "open_thread" and a.params.get("with") == "abuela"], [])

    def test_a_final_offer_in_a_manual_thread_is_not_accepted(self):
        th = S.thread([("d", 2, 27, S.CARD), ("u", 3, 12), ("d", 4, 13, S.CARD)], final=True)
        self.assertEqual([a.kind for a in acts({"manual_threads": ["10"]}, th)
                          if a.kind in ("thread_message", "close_thread", "accept_offer")], [])


if __name__ == "__main__":
    unittest.main()
