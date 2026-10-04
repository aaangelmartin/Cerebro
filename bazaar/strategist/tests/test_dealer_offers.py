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

    def test_a_dealer_offer_that_already_expired_stays_in_the_picture_from_the_feed(self):
        """A dealer's offer lives about 4 ticks; the plan runs later, so the last one of each thread is kept."""
        def msg(tick, offer):
            return {"type": "thread.message", "tick": tick, "payload": {"thread": offer["thread"], "offer": offer}}
        sell = {"id": 16531, "maker": "pilar", "to": "t10", "thread": 1637, "status": "open", "final": True,
                "expires_tick": 1104, "give": {"cash": 84}, "want": {"assets": [{"id": 5, "ref": "LAV-04"}]}}
        feed = [
            msg(1000, dict(sell, id=1, thread=9)),                                   # too old
            msg(1098, dict(sell, id=16500, give={"cash": 80}, final=False)),         # replaced by the next one
            msg(1100, sell),
            msg(1100, dict(sell, id=7, to="t07", thread=50)),                        # another team's thread
            msg(1101, {"id": 8, "maker": "t10", "to": "pilar", "thread": 1637, "give": {}, "want": {"cash": 90}}),
            msg(1102, {"id": 13298, "maker": "picaros", "to": "t10", "thread": 1221, "status": "open",
                       "give": {"types": ["card:MAL-09"]}, "want": {"cash": 60}}),   # still open below
        ]
        offers = [{"id": 13298, "maker": "picaros", "to": "t10", "status": "open", "thread": 1221,
                   "give": {"cash": 0, "types": ["card:MAL-09"]}, "want": {"cash": 60}}]
        got = A.dealer_offers_to_us(offers, self.me, self.catalog, feed, now_tick=1110)
        self.assertEqual([(o["offer"], o["state"]) for o in got], [(13298, "open"), (16531, "gone")])
        gone = got[1]
        self.assertEqual((gone["dealer"], gone["thread"], gone["seen_tick"], gone["final"]), ("pilar", 1637, 1100, True))
        self.assertEqual(gone["value_gain"], 80.0)                  # 84 P for a spare worth 4
        self.assertIn("no longer open", gone["how_to_take"])
        # without a feed nothing changes
        self.assertEqual([o["offer"] for o in A.dealer_offers_to_us(offers, self.me, self.catalog)], [13298])

    def test_the_event_line_carries_the_terms(self):
        row = A.dealer_offers_to_us([{"id": 16531, "maker": "pilar", "to": "t10", "thread": 1637, "status": "open",
                                      "final": True, "expires_tick": 1104, "give": {"cash": 84},
                                      "want": {"assets": [{"id": 5, "ref": "LAV-04"}]}}], self.me, self.catalog)[0]
        line = A.dealer_offer_line(row)
        for part in ("pilar", "thread 1637", "84 P", "LAV-04", "gain +80.0", "FINAL", "expires t1104"):
            self.assertIn(part, line)


class OfferEventTest(unittest.TestCase):
    def test_the_offer_event_of_a_dealer_says_card_price_and_gain(self):
        import json
        import tempfile
        from pathlib import Path
        from bazaar.strategist import run as R
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d)
            (rec / "me.json").write_text(json.dumps({"assets": [{"id": 5, "ref": "LAV-04", "your_value": 4.0}]}))
            w = R.EventDetector.__new__(R.EventDetector)
            w.record = rec
            (rec / "my_offers.json").write_text(json.dumps({"offers": []}))
            before = w.snapshot()
            (rec / "my_offers.json").write_text(json.dumps({"offers": [
                {"id": 16531, "maker": "pilar", "to": "t10", "thread": 1637, "status": "open", "final": True,
                 "expires_tick": 1104, "give": {"cash": 84}, "want": {"assets": [{"id": 5, "ref": "LAV-04"}]}},
                {"id": 9, "maker": "t05", "to": "t10", "status": "open", "give": {"cash": 3}, "want": {}}]}))
            texts = [e["text"] for e in R.EventDetector.diff(before, w.snapshot()) if e["kind"] == "offer"]
        dealer = next(t for t in texts if "#16531" in t)
        self.assertIn("84 P", dealer)
        self.assertIn("LAV-04", dealer)
        self.assertIn("gain +80.0", dealer)
        self.assertIn("offer #9 addressed to us by t05", texts)      # a team offer keeps its short form


if __name__ == "__main__":
    unittest.main()
