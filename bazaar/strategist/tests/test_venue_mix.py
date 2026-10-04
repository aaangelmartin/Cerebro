import unittest

from bazaar.strategist.analysis import venue_mix


def listed(venue, maker, to=None, swap=False):
    give = {"assets": [{"ref": "RET-01"}]}
    want = {"types": ["card:MAL-09"]} if swap else {"cash": 9}
    return {"type": "offer.listed", "actor": maker,
            "payload": {"venue": venue, "offer": {"id": 1, "maker": maker, "to": to, "give": give, "want": want}}}


class VenueMixTest(unittest.TestCase):
    def test_public_vs_addressed_and_fills(self):
        feed = [listed("v02", "t14"), listed("v02", "t14"), listed("v02", "t13", swap=True),
                listed("v07", "t08", to="t02"), listed("v07", "t05", to="t03"), listed("v07", "t06"),
                listed("rastro", "t01"),
                {"type": "settlement", "payload": {"venue": "v02", "parties": ["t14", "t09"], "cash": 9}},
                {"type": "settlement", "payload": {"venue": "v07", "parties": ["t04", "t09"], "price": 28}}]
        out = venue_mix(feed, [{"venue": "v02", "owner": "t12"}, {"venue": "v07", "owner": "t10"}], "v07")
        self.assertEqual((out["ours"]["public"], out["ours"]["addressed"], out["ours"]["fills"]), (1, 2, 1))
        self.assertEqual(out["ours"]["public_share"], 0.33)
        top = out["top"][0]
        self.assertEqual((top["venue"], top["owner"], top["public"], top["swaps"], top["fills"]), ("v02", "t12", 3, 1, 1))
        self.assertEqual(top["makers"][0], ("t14", 2))

    def test_no_venue_rows(self):
        self.assertEqual(venue_mix([], [], "v07"), {"ours": None, "top": []})


if __name__ == "__main__":
    unittest.main()
