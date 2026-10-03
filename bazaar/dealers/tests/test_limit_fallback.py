"""code-134e153f: a deal the bot never evaluated (closed by hand, settled while paused) still gets a capture."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bazaar.dealers.profiles import ProfileStore


def store(profiles: dict | None = None, deals: list | None = None) -> ProfileStore:
    path = Path(tempfile.mkdtemp()) / "dealer_memory.json"
    path.write_text(json.dumps({"profiles": profiles or {}, "deals": deals or []}))
    return ProfileStore(path, seed=False)


PICAROS = {"picaros": {"buy:rare": {"limit_ratio": [1.0, 1.0, 0.74, 0.77, 0.82]},
                       "sell:common": {"limit_ratio": [1.0, 1.25]}, "?": {"limit_ratio": [1.0]}}}


class LimitFallbackTest(unittest.TestCase):
    def test_hand_closed_buy_without_a_limit_scores_its_slot(self):
        s = store(PICAROS)
        d = s.record_deal("picaros", 4, "?", "MAL-09", 73, 57, None, True, None, thread=1400, tick=967)
        self.assertEqual(d["limit_est"], 54.02)             # the lowest the dealer was pushed: 73 * 0.74
        self.assertEqual(d["capture"], 0.843)
        self.assertEqual(s.ladder(4), [0.843, 0.0, 0.0])

    def test_sell_uses_the_highest_the_dealer_paid(self):
        d = store(PICAROS).record_deal("picaros", 4, "?", "MAL-02", 4, 5, None, False, 3.0, thread=7)
        self.assertEqual((d["limit_est"], d["capture"]), (5.0, 1.0))

    def test_a_known_kind_keeps_to_its_own_samples_and_a_given_limit_wins(self):
        s = store(PICAROS)
        self.assertEqual(s.limit_fallback("picaros", "sell:common", False, 4), 5.0)
        d = s.record_deal("picaros", 4, "buy:rare", "RET-09", 73, 57, 49.0, True, 77.0, thread=8)
        self.assertEqual((d["limit_est"], d["capture"]), (49.0, 0.667))

    def test_unknown_dealer_falls_back_to_the_traits_prior(self):
        d = store().record_deal("banco", 5, "?", "sobre_oro", 546, 500, None, True, None, thread=9)
        self.assertGreater(d["capture"], 0.0)

    def test_a_deal_at_the_opening_price_still_scores_zero(self):
        d = store(PICAROS).record_deal("picaros", 4, "?", "MAL-09", 73, 73, None, True, None, thread=10)
        self.assertEqual((d["capture"], d["negotiated"]), (0.0, False))

    def test_stored_deals_without_a_limit_are_repaired_on_load(self):
        old = {"dealer": "picaros", "level": 4, "kind": "?", "item": "MAL-09", "opening": 73, "price": 57,
               "limit_est": None, "capture": 0.0, "side": "buy", "thread": 1400, "negotiated": True, "at": 1.0}
        s = store(PICAROS, [old])
        self.assertEqual(s.data["deals"][0]["capture"], 0.843)
        self.assertEqual(s.ladder(4), [0.843, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
