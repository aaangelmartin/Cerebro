"""Outbox request code-340d9d26: a dealer standing 1 P outside our limit is not abandoned while we still have
messages and its ladder level has an empty slot; we restate our price, one message per tick, never beyond it."""
from __future__ import annotations

import unittest

from bazaar.dealers.domain import DealersDomain
from bazaar.dealers.tests import test_domain as T
from bazaar.dealers.threads import parse_thread

buy_thread, domain = T.buy_thread, T.domain
SIT, CTX = T.AuditFixes().sit, T.AuditFixes().ctx


def limit_of(dom) -> int:
    plan = dom._prepare(SIT(tick=3, threads=[buy_thread(10, theirs=((2, 60),))]), CTX(3))
    return plan.infos[0].limit


def stuck(lim, gap=1, n_ours=3, final=False):
    """We reached our cap `lim`; the dealer answered twice at lim + gap. Our turn at the returned tick."""
    ours = [(3 + 2 * i, lim - (n_ours - 1 - i)) for i in range(n_ours)]
    theirs = [(2, lim + 20)] + [(4 + 2 * i, lim + gap + (1 if i < n_ours - 2 else 0)) for i in range(n_ours - 1)]
    theirs.append((ours[-1][0] + 1, lim + gap))
    return buy_thread(10, theirs=tuple(theirs), ours=tuple(ours), final=final), theirs[-1][0] + 1


def acts_for(dom, th, tick, **budget):
    return [a for a in dom.fallback(SIT(tick=tick, threads=[th]), CTX(tick, **budget))
            if a.kind in ("thread_message", "close_thread", "accept_offer")]


class HoldNearLimit(unittest.TestCase):
    def test_holds_our_price_instead_of_closing(self):
        dom = domain()
        lim = limit_of(dom)
        th, tick = stuck(lim)
        acts = acts_for(dom, th, tick)
        self.assertEqual([a.kind for a in acts], ["thread_message"])
        self.assertEqual(acts[0].params["price"], lim)                     # never beyond our limit
        self.assertIn("hold our price", acts[0].reason)

    def test_wording_changes_between_holds(self):
        dom = domain()
        lim = limit_of(dom)
        a3 = acts_for(dom, *stuck(lim, n_ours=3))[0]
        a4 = acts_for(dom, *stuck(lim, n_ours=4))[0]
        self.assertEqual(a3.params["price"], a4.params["price"])
        self.assertNotEqual(a3.params["text"], a4.params["text"])

    def test_one_message_per_tick(self):
        dom = domain()
        th, tick = stuck(limit_of(dom))
        self.assertFalse(acts_for(dom, th, tick, messages={"thread:10": 1}))

    def test_closes_once_the_messages_are_used(self):
        dom = domain()
        th, tick = stuck(limit_of(dom), n_ours=5)
        self.assertEqual([a.kind for a in acts_for(dom, th, tick)], ["close_thread"])

    def test_closes_when_the_level_has_no_empty_slot(self):
        dom = domain()
        lim = limit_of(dom)
        level = dom._prepare(SIT(tick=3, threads=[buy_thread(10, theirs=((2, 60),))]), CTX(3)).infos[0].level
        dom.store.data["deals"].extend({"dealer": "other", "at": 0, "level": level, "negotiated": True, "capture": 0.5} for _ in range(3))
        th, tick = stuck(lim)
        self.assertEqual([a.kind for a in acts_for(dom, th, tick)], ["close_thread"])

    def test_far_from_our_limit_still_closes(self):
        dom = domain()
        lim = limit_of(dom)
        th, tick = stuck(lim, gap=max(3, int(0.05 * lim) + 2))
        self.assertNotIn("thread_message", [a.kind for a in acts_for(dom, th, tick)])

    def test_final_offer_outside_our_limit_still_closes(self):
        dom = domain()
        th, tick = stuck(limit_of(dom), final=True)
        self.assertEqual([a.kind for a in acts_for(dom, th, tick)], ["close_thread"])

    def test_silent_dealer_still_closes(self):
        dom = domain()
        lim = limit_of(dom)
        th = buy_thread(10, theirs=((2, lim + 20), (4, lim + 1)), ours=((3, lim - 1), (5, lim)))
        self.assertEqual([a.kind for a in acts_for(dom, th, 9)], ["close_thread"])

    def test_offer_inside_our_limit_is_accepted_not_closed(self):
        dom = domain()
        lim = limit_of(dom)
        th = buy_thread(10, theirs=((2, lim + 20), (4, lim + 1), (6, lim)), ours=((3, lim - 1), (5, lim)))
        self.assertEqual([a.kind for a in acts_for(dom, th, 7)], ["accept_offer"])

    def test_claude_cannot_close_a_thread_we_hold(self):
        dom = domain()
        th, tick = stuck(limit_of(dom))
        plan = dom._prepare(SIT(tick=tick, threads=[th]), CTX(tick))
        self.assertEqual(plan.infos[0].move.kind, "hold")
        acts = dom._apply_llm(plan, CTX(tick), {"threads": [{"thread": 10, "move": "close", "reason": "stuck"}]})
        self.assertEqual([a.kind for a in acts if a.kind != "open_thread"], ["thread_message"])

    def test_near_limit_scales_with_the_price(self):
        near = lambda theirs, lim: DealersDomain._near_limit(  # noqa: E731
            parse_thread(buy_thread(1, theirs=((2, theirs),))), lim)
        self.assertTrue(near(6, 5))             # 1 P on a small deal (tick 872: 4 against 5)
        self.assertFalse(near(7, 5))
        self.assertTrue(near(77, 74))           # 5 % of 74 = 3 P (MAL-09 from Los Picaros)
        self.assertFalse(near(78, 74))
        self.assertFalse(near(74, 74))          # inside our limit: that is an accept, not a hold


if __name__ == "__main__":
    unittest.main()
