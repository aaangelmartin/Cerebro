"""A dealer's opening ask is where it starts, not where it stops (Sunday, tick 1519: the code closed a brain order
for SAL-10 at Los Pícaros' opening 73 with a cap of 59; they sold that card at 59 seven ticks later). Threads we
closed without a counter teach nothing about a dealer's limit and do not count as refusals."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bazaar.dealers.domain import STUCK_AFTER, DealersDomain
from bazaar.dealers.evaluate import SCENARIOS, make_catalog, make_ctx, make_sit
from bazaar.dealers.profiles import UNTESTED_FIX, ProfileStore
from bazaar.dealers.simulator import DealerWorld
from bazaar.dealers.threads import ThreadView


def view(theirs, ours, last_sender="dealer", final=False):
    return ThreadView(id=1, dealer="picaros", side="buy", topic={"buy": {"card": "SAL-10"}}, item="SAL-10",
                      created_tick=1518, theirs=list(theirs), ours=list(ours), opening=theirs[0],
                      their_ticks=[1518 + i for i in range(len(theirs))],
                      our_ticks=[1518 + i for i in range(len(ours))], last_sender=last_sender, final=final,
                      n_messages=len(theirs) + len(ours), last_dealer_tick=1519, last_our_tick=1518 if ours else None)


def domain(orders=()):
    dom = DealersDomain(store=ProfileStore(Path(tempfile.mkdtemp()) / "m.json"), catalog=make_catalog(), use_llm=False)
    dom._brain_orders = lambda: list(orders)
    dom._note_order = lambda *a, **kw: None
    return dom


class OpeningIsNotAStopTest(unittest.TestCase):
    def test_the_opening_ask_alone_never_closes_a_brain_order(self):
        # the live case: opening 73, cap 59, the profile's estimate says "it stops at 73"
        self.assertEqual(DealersDomain._stale_or_hopeless(view([73], []), 59, 73.0, 1519, ordered=True), "")
        # ...nor while our ladder is still below our own limit
        self.assertEqual(DealersDomain._stale_or_hopeless(view([73, 70], [40]), 59, 73.0, 1521, ordered=True), "")

    def test_it_walks_away_once_the_dealer_heard_our_limit_and_stayed_above(self):
        why = DealersDomain._stale_or_hopeless(view([73, 72, 71], [50, 59]), 59, 73.0, 1523, ordered=True)
        self.assertIn("dealer stops near 73", why)
        # the code's own threads keep the quick rule: a dealer has one slot per team
        self.assertIn("dealer stops near 73", DealersDomain._stale_or_hopeless(view([73], []), 59, 73.0, 1519))

    def test_a_brain_order_bids_instead_of_closing_at_the_opening(self):
        scen = SCENARIOS[3]                                        # chato sells LAV-10, opening 97, worth 112 to us
        w = DealerWorld(seed=1)
        w.open(scen.dealer, scen.topic, scen.kind, scen.item_type)
        w.advance()
        dom = domain([{"dealer": "chato", "action": "buy", "ref": "LAV-10", "open": None, "bound": 70,
                       "max_messages": 4, "why": ""}])
        for _ in range(9):                                         # what Sunday's threads had taught the profile
            dom.store.learn_thread("chato", "buy:rare", 97, [97], [], False, True)
        info = dom._prepare(make_sit(w, scen), make_ctx(w.tick)).infos[0]
        self.assertEqual(info.force_close, "")
        self.assertEqual(info.move.kind, "price")
        self.assertLessEqual(info.move.price, 70)


class UntestedThreadsTeachNothingTest(unittest.TestCase):
    T = {"dealer": "picaros", "side": "buy", "item": "SAL-10", "kind": "buy:rare", "opening": 73, "final": False}

    def test_a_thread_closed_at_the_opening_is_not_a_refusal_nor_a_limit(self):
        dom = domain()
        before = list(dom.store.data["profiles"].get("picaros", {}).get("buy:rare", {}).get("limit_ratio") or [])
        for i in range(STUCK_AFTER + 1):
            dom._finish(100 + i, dict(self.T, theirs=[73], ours=[]), {"status": "closed"}, {}, {}, 1520 + i)
        self.assertEqual(dom.store.data.get("stuck") or {}, {})
        self.assertIsNone(dom._stuck("picaros", "buy:rare", 59, 1530))
        after = dom.store.data["profiles"].get("picaros", {}).get("buy:rare", {}).get("limit_ratio") or []
        self.assertEqual(after, before)

    def test_a_thread_that_heard_our_bids_still_counts(self):
        dom = domain()
        for i in range(STUCK_AFTER):
            dom._finish(200 + i, dict(self.T, theirs=[73, 70, 68], ours=[50, 59]), {"status": "closed"}, {}, {},
                        1520 + i)
        self.assertEqual(dom._stuck("picaros", "buy:rare", 59, 1530), 68.0)
        self.assertIn(round(68 / 73, 4), dom.store.data["profiles"]["picaros"]["buy:rare"]["limit_ratio"])

    def test_what_those_threads_taught_is_forgotten_once(self):
        path = Path(tempfile.mkdtemp()) / "m.json"
        path.write_text(json.dumps({
            "profiles": {"picaros": {"buy:rare": {"open": [73, 73, 73], "limit_ratio": [1.0, 0.75, 1.0]}}},
            "stuck": {"picaros|buy:rare": {"n": 2, "tick": 1520, "floor": 73.0}}, "seeds_applied": []}))
        store = ProfileStore(path)
        self.assertNotIn(1.0, store.data["profiles"]["picaros"]["buy:rare"]["limit_ratio"])
        self.assertIn(0.75, store.data["profiles"]["picaros"]["buy:rare"]["limit_ratio"])
        self.assertEqual(store.data["stuck"], {})
        self.assertIn(UNTESTED_FIX, store.data["seeds_applied"])
        store.data["profiles"]["picaros"]["buy:rare"]["limit_ratio"].append(1.0)   # a real deal at the opening, later
        store.save()
        self.assertIn(1.0, ProfileStore(path).data["profiles"]["picaros"]["buy:rare"]["limit_ratio"])


if __name__ == "__main__":
    unittest.main()
