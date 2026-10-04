"""The market reads the catalog again during the day: Chamberí is released on Sunday morning, hours after the bot
started, and a copy read once would call its cards unreleased until the next restart."""
import unittest

from bazaar.market import domain as D


def cat(released: bool) -> dict:
    return {"sets": [{"id": "CHA", "released": released,
                      "cards": [{"id": "CHA-01", "rarity": "common", "book": 10, "page": True}]}]}


class GW:
    def __init__(self):
        self.docs, self.calls, self.fail = [cat(False), cat(True)], 0, False

    def get(self, path, **kw):
        self.calls += 1
        if self.fail:
            raise OSError("down")
        return self.docs[min(self.calls - 1, len(self.docs) - 1)]


class CatalogRefreshTest(unittest.TestCase):
    def test_a_set_released_after_the_start_is_seen(self):
        gw = GW()
        d = D.MarketDomain(gw=gw, use_llm=False)
        self.assertFalse(d.catalog()["sets"][0]["released"])
        self.assertFalse(d.catalog()["sets"][0]["released"])
        self.assertEqual(gw.calls, 1)                              # inside the TTL: no second read
        d._catalog_at -= D.CATALOG_TTL_S + 1
        d._catalog_tried -= 60
        self.assertTrue(d.catalog()["sets"][0]["released"])
        self.assertEqual(gw.calls, 2)

    def test_a_failed_read_keeps_the_last_copy_and_is_not_hammered(self):
        gw = GW()
        d = D.MarketDomain(gw=gw, use_llm=False)
        d.catalog()
        d._catalog_at -= D.CATALOG_TTL_S + 1
        d._catalog_tried -= 60
        gw.fail = True
        self.assertFalse(d.catalog()["sets"][0]["released"])
        self.assertFalse(d.catalog()["sets"][0]["released"])
        self.assertEqual(gw.calls, 2)                              # one failed try, then 30 s of quiet

    def test_a_catalog_given_at_the_start_counts_as_fresh(self):
        gw = GW()
        d = D.MarketDomain(gw=gw, catalog=cat(False), use_llm=False)
        d.catalog()
        self.assertEqual(gw.calls, 0)


if __name__ == "__main__":
    unittest.main()
