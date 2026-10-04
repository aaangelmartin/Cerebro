"""A card with no copy left at the dealers is not asked for again (t1722-1750: seven Pícaros threads for SAL-11)."""
from __future__ import annotations

import time
import types
import unittest

from bazaar.dealers.domain import DealersDomain


def dom():
    d = DealersDomain.__new__(DealersDomain)
    d._sold_out = {}
    return d


def values(**cards):
    return types.SimpleNamespace(cards=cards)


class SoldOut(unittest.TestCase):
    def test_every_printed_copy_out_means_no_stock(self):
        self.assertTrue(dom()._no_stock("picaros", "SAL-11", values(**{"SAL-11": {"print_run": 9, "minted": 9}})))

    def test_copies_left_in_the_catalog_mean_stock(self):
        self.assertFalse(dom()._no_stock("picaros", "SAL-08", values(**{"SAL-08": {"print_run": 90, "minted": 23}})))

    def test_a_dealer_that_said_sold_out_is_not_asked_for_half_an_hour(self):
        d = dom()
        d._sold_out[("picaros", "SAL-10")] = time.time() - 60
        v = values(**{"SAL-10": {"print_run": 30, "minted": 12}})
        self.assertTrue(d._no_stock("picaros", "SAL-10", v))
        self.assertFalse(d._no_stock("abuela", "SAL-10", v))
        d._sold_out[("picaros", "SAL-10")] = time.time() - 1900
        self.assertFalse(d._no_stock("picaros", "SAL-10", v))

    def test_a_card_the_catalog_does_not_know_is_not_blocked(self):
        self.assertFalse(dom()._no_stock("picaros", "CHA-11", values()))
        self.assertFalse(dom()._no_stock("picaros", "CHA-11", values(**{"CHA-11": {"print_run": None, "minted": 2}})))


if __name__ == "__main__":
    unittest.main()
