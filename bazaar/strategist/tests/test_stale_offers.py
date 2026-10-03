import unittest

from bazaar.strategist.analysis import stale_offers


def settlement(tick, frm, to, ref, price, rarity="epic", persona=None):
    return {"type": "settlement", "tick": tick, "payload": {
        "tick": tick, "kind": "trade", "parties": [frm, to], "persona": persona, "price": price,
        "items": [{"id": 787, "ref": ref, "rarity": rarity, "frm": frm, "to": to}]}}


class StaleOffersTest(unittest.TestCase):
    def test_swap_for_a_card_the_target_sold_is_stale(self):
        mine = [{"id": 8084, "maker": "t10", "to": "t08", "status": "open", "created_tick": 549,
                 "give": {"assets": [{"id": 797, "ref": "SAL-10"}]}, "want": {"types": ["card:LAV-11"]}},
                {"id": 9000, "maker": "t10", "to": "t17", "status": "open",
                 "give": {"assets": [{"id": 1, "ref": "MAL-02"}]}, "want": {"cash": 6}}]
        out = stale_offers(mine, [settlement(550, "t08", "pilar", "LAV-11", 140, persona="pilar")])
        self.assertEqual([x["offer"] for x in out["cancel_these"]], [8084])
        self.assertIn("pilar", out["cancel_these"][0]["why"])
        self.assertEqual(out["rare_cards_gone_to_dealers"][0]["card"], "LAV-11")

    def test_not_stale_if_the_target_got_another_copy(self):
        mine = [{"id": 1, "maker": "t10", "to": "t08", "status": "open", "want": {"types": ["card:MAL-10"]}}]
        feed = [settlement(500, "t08", "t17", "MAL-10", 70, rarity="rare"),
                settlement(510, "t09", "t08", "MAL-10", 65, rarity="rare")]
        self.assertEqual(stale_offers(mine, feed)["cancel_these"], [])

    def test_no_feed_no_stale(self):
        self.assertEqual(stale_offers([], [])["cancel_these"], [])


if __name__ == "__main__":
    unittest.main()
