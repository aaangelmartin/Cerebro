"""A dealer that will not go below a price above our max is not asked again and again (Sunday, round 3: the
brain ordered SAL-06/07 from Abuela at 21-22 P while she stopped near 26, seven threads in five minutes), and the
last threads of the hour with a gift-giving dealer wait for its gift window."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from bazaar.dealers import gifts
from bazaar.dealers.domain import GIFT_RESERVE, STUCK_AFTER, STUCK_TICKS, DealersDomain
from bazaar.dealers.evaluate import make_catalog, make_ctx
from bazaar.dealers.profiles import CONV_QUOTA, ProfileStore

ABUELA = {"id": "abuela", "name": "Abuela Carmen", "kind": "grandma", "level": 1, "status": "active",
          "open_to_all": True, "traits": {"patience": 0.85, "generosity": 0.8, "shrewdness": 0.2},
          "menu": {"sells": [{"rarity": "common", "sets": "released", "list_price": 10},
                             {"rarity": "uncommon", "sets": "released", "list_price": 25}],
                   "buys": [{"rarity": "common", "sets": "released"}], "deals_per_team_per_hour": 8}}


def domain(orders):
    dom = DealersDomain(store=ProfileStore(Path(tempfile.mkdtemp()) / "m.json"), catalog=make_catalog(), use_llm=False)
    dom._brain_orders = lambda: list(orders)
    notes = []
    dom._note_order = lambda o, status, detail="", tick=None, **kw: notes.append((o["ref"], status, detail))
    return dom, notes


def sit(tick, cash=2000):
    return SimpleNamespace(tick=tick, me={"id": "t10", "cash": cash, "unlocked": ["abuela"],
                                          "affinity": {"LAV": 1.6, "MAL": 1.3, "RET": 1.1, "SAL": 0.9, "LAT": 0.5},
                                          "assets": []},
                           threads=[], my_offers=[], dealers=[ABUELA], limits={"max_open_threads_per_team": 6},
                           feed_new=[], closed_threads=[])


def order(ref="SAL-06", bound=21):
    return {"dealer": "abuela", "action": "buy", "ref": ref, "open": None, "bound": bound, "max_messages": 4, "why": ""}


def opens(dom, tick, set_id="SAL"):
    """Threads opened this tick; by default only those for the set of the ordered cards (the domain's own
    candidates, such as a LAV uncommon well under our value, are another matter)."""
    got = [a for a in dom.fallback(sit(tick), make_ctx(tick)) if a.kind == "open_thread"]
    return [a for a in got if set_id is None
            or str(((a.params.get("topic") or {}).get("buy") or {}).get("card", "")).startswith(set_id)]


class StuckDealerTest(unittest.TestCase):
    def test_an_order_opens_until_the_dealer_refused_twice_in_a_row(self):
        dom, notes = domain([order()])
        gifts.record(dom.store.data, "abuela", 1000)                 # no gift window in the way
        self.assertEqual(len(opens(dom, 1010)), 1)
        dom._note_stuck("abuela", "buy:uncommon", False, [29, 27, 26], None, 1011)
        self.assertEqual(len(opens(dom, 1012)), 1)                   # one refusal is not a pattern
        dom._note_stuck("abuela", "buy:uncommon", False, [29, 26], None, 1013)
        self.assertEqual(STUCK_AFTER, 2)
        notes.clear()
        self.assertEqual(opens(dom, 1014), [])
        self.assertTrue(any(ref == "SAL-06" and status == "skipped" and "did not go below 26" in detail
                            for ref, status, detail in notes), notes)

    def test_the_other_card_of_the_same_kind_and_a_slightly_higher_cap_do_not_dodge_it(self):
        dom, _ = domain([order("SAL-07", bound=22)])                 # what the brain did live: 21 -> 22, SAL-06 -> 07
        gifts.record(dom.store.data, "abuela", 1000)
        for t in (1011, 1013):
            dom._note_stuck("abuela", "buy:uncommon", False, [26], None, t)
        self.assertEqual(opens(dom, 1014), [])

    def test_it_asks_again_after_a_while_or_after_a_deal(self):
        dom, _ = domain([order()])
        gifts.record(dom.store.data, "abuela", 1000)
        for t in (1011, 1013):
            dom._note_stuck("abuela", "buy:uncommon", False, [26], None, t)
        self.assertEqual(opens(dom, 1013 + STUCK_TICKS - 1), [])
        self.assertEqual(len(opens(dom, 1013 + STUCK_TICKS)), 1)
        for t in (1011, 1013):
            dom._note_stuck("abuela", "buy:uncommon", False, [26], None, t)
        dom._note_stuck("abuela", "buy:uncommon", True, [20], None, 1014)        # a deal: the count starts over
        self.assertIsNone(dom._stuck("abuela", "buy:uncommon", 21, 1015))

    def test_a_max_that_reaches_the_price_it_stopped_at_goes_ahead(self):
        dom, _ = domain([])
        for t in (1011, 1013):
            dom._note_stuck("abuela", "buy:common", False, [9, 8], None, t)
        self.assertEqual(dom._stuck("abuela", "buy:common", 7, 1014), 8.0)
        self.assertIsNone(dom._stuck("abuela", "buy:common", 8, 1014))
        self.assertIsNone(dom._stuck("abuela", "buy:rare", 7, 1014))             # another kind of card is another price

    def test_selling_and_packs_are_not_counted(self):
        dom, _ = domain([])
        dom._note_stuck("abuela", "sell:common", False, [3], None, 1011)
        dom._note_stuck("abuela", "buy:pack", False, [30], None, 1011)
        self.assertEqual(dom.store.data.get("stuck") or {}, {})


class GiftReserveTest(unittest.TestCase):
    def _used(self, dom, n):
        for _ in range(n):
            dom.store.note_open("abuela", time.time())

    def test_the_last_threads_of_the_hour_wait_for_the_gift_window(self):
        dom, _ = domain([order(bound=21)])
        gifts.record(dom.store.data, "abuela", 1400)                 # next gift possible at 1640
        self._used(dom, CONV_QUOTA - GIFT_RESERVE)                   # two threads left this hour
        self.assertEqual(opens(dom, 1500, None), [])                 # the window opens within the hour: keep them
        got = opens(dom, 1640, None)                                     # the window is open: the thread goes out
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].params["with"], "abuela")

    def test_with_quota_to_spare_orders_open_as_usual(self):
        dom, _ = domain([order(bound=21)])
        gifts.record(dom.store.data, "abuela", 1400)
        self._used(dom, CONV_QUOTA - GIFT_RESERVE - 1)               # three left
        self.assertEqual(len(opens(dom, 1500, None)), 1)


if __name__ == "__main__":
    unittest.main()
