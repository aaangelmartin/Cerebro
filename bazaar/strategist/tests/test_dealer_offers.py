import unittest

from bazaar.strategist import analysis as A


class DealerOffersTest(unittest.TestCase):
    me = {"affinity": {"MAL": 1.3, "LAV": 1.6},
          "assets": [{"id": 5, "ref": "LAV-04", "your_value": 4.0, "kind": "card", "rarity": "common"},
                     {"id": 6, "ref": "LAV-04", "your_value": 16.0, "kind": "card", "rarity": "common"}]}
    catalog = {"sets": [{"id": "MAL", "released": True, "cards": [
        {"id": "MAL-09", "rarity": "rare", "book": 70, "page": True, "hidden": False}]}]}

    def test_dealer_thread_offers_are_listed_with_terms_and_value(self):
        offers = [
            # Pícaros sell us MAL-09 for 60 inside a thread
            {"id": 13298, "maker": "picaros", "to": "t10", "status": "open", "thread": 1221, "final": True,
             "expires_tick": 900, "give": {"cash": 0, "types": ["card:MAL-09"]}, "want": {"cash": 60}},
            # Pícaros buy our spare LAV-04 for 5
            {"id": 13325, "maker": "picaros", "to": "t10", "status": "open", "thread": 1222,
             "give": {"cash": 5}, "want": {"assets": [{"id": 5, "ref": "LAV-04"}]}},
            # a team offer and one of ours: not dealer offers
            {"id": 1, "maker": "t05", "to": "t10", "status": "open", "thread": None, "give": {"cash": 20},
             "want": {"types": ["card:LAV-04"]}},
            {"id": 2, "maker": "t10", "to": "picaros", "status": "open", "thread": 1221, "give": {}, "want": {"cash": 9}},
            {"id": 3, "maker": "picaros", "to": "t10", "status": "cancelled", "thread": 1221, "give": {"cash": 4},
             "want": {"assets": [{"id": 5, "ref": "LAV-04"}]}},
        ]
        got = A.dealer_offers_to_us(offers, self.me, self.catalog)
        self.assertEqual([o["offer"] for o in got], [13298, 13325])
        buy, sell = got
        self.assertEqual((buy["dealer"], buy["thread"], buy["final"], buy["expires_tick"]), ("picaros", 1221, True, 900))
        self.assertEqual(buy["they_give"]["cards"][0]["ref"], "MAL-09")
        self.assertEqual(buy["we_give"]["cash"], 60)
        self.assertGreater(buy["value_gain"], 0)                    # 70 x 1.3 = 91 against 60
        self.assertEqual(sell["they_give"]["cash"], 5)
        self.assertEqual(sell["value_gain"], 1.0)                   # 5 P for a spare worth 4
        self.assertTrue(all(o["kind"] == "dealer_offer" for o in got))
        # team offers stay in offers_to_us only
        self.assertEqual([o["offer"] for o in A.offers_to_us(offers, self.me, {})], [1])


if __name__ == "__main__":
    unittest.main()
