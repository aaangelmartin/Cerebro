"""code-238c0003: the gift probe does not open a buy thread for a card we already hold (t1604 MAL-06, t1628 MAL-08)."""
from __future__ import annotations

import types
import unittest

from bazaar.dealers.domain import Candidate, DealersDomain


def cand(cid, kind, item, points=1.0):
    return Candidate(id=cid, dealer="abuela", topic={}, kind=kind, item=item, name=item, value=10.0, limit=5,
                     est_open=9.0, est_limit=6.0, exp_price=6.0, exp_capture=0.5, points=points, level=1)


def values(*held):
    return types.SimpleNamespace(held={ref: [1] for ref in held})


class HeldProbe(unittest.TestCase):
    def test_a_card_we_hold_is_not_the_gift_probe_while_another_will_do(self):
        probes = [cand("c1", "buy:uncommon", "MAL-06", 9.0), cand("c2", "buy:uncommon", "SAL-08", 1.0)]
        kept = DealersDomain._not_held_first(probes, values("MAL-06", "MAL-08"))
        self.assertEqual([c.item for c in kept], ["SAL-08"])

    def test_a_sale_of_a_spare_is_never_dropped(self):
        probes = [cand("c1", "buy:uncommon", "MAL-06"), cand("c2", "sell:common", "MAL-01")]
        kept = DealersDomain._not_held_first(probes, values("MAL-06", "MAL-01"))
        self.assertEqual([c.item for c in kept], ["MAL-01"])

    def test_with_nothing_else_the_gift_thread_still_opens(self):
        probes = [cand("c1", "buy:uncommon", "MAL-06")]
        self.assertEqual(DealersDomain._not_held_first(probes, values("MAL-06")), probes)

    def test_cards_we_do_not_hold_are_untouched(self):
        probes = [cand("c1", "buy:uncommon", "SAL-08"), cand("c2", "buy:common", "CHA-02")]
        self.assertEqual(DealersDomain._not_held_first(probes, values("MAL-06")), probes)


if __name__ == "__main__":
    unittest.main()
