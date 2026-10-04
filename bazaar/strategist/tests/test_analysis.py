import json
import tempfile
import time
import unittest
from pathlib import Path

from bazaar.strategist import analysis as A


class AnalysisTest(unittest.TestCase):
    def test_rivals_from_settlements(self):
        now = time.time()
        feed = [
            {"ts": now - 60, "type": "settlement", "payload": {"parties": ["t12", "abuela"], "persona": "abuela",
                                                             "price": 21, "items": [{"ref": "RET-06", "frm": "abuela", "to": "t12"}]}},
            {"ts": now - 50, "type": "thread.message", "payload": {"team": "t12", "with": "abuela"}},
            {"ts": now - 99999, "type": "settlement", "payload": {"parties": ["t12", "abuela"], "price": 1,
                                                                "items": [{"ref": "OLD-01", "frm": "abuela", "to": "t12"}]}},
        ]
        lb = {"teams": [{"team": "t12", "score": 30, "negotiating": 20, "market": 10, "rank": 1},
                        {"team": "t10", "score": 15, "negotiating": 10, "market": 5, "rank": 9}]}
        cat = {"rarities": {"uncommon": {"book": 25}}, "sets": [{"cards": [{"id": "RET-06", "rarity": "uncommon"}]}]}
        r = A.rivals(feed, lb, cat, now - 3600)["teams"]["t12"]
        self.assertEqual(r["buys"], 1)
        self.assertEqual(r["last_buys"][0], {"ref": "RET-06", "price": 21, "book": 25, "via": "abuela", "from": "abuela"})
        self.assertEqual(r["sets_bought"], {"RET": 1})
        self.assertEqual(r["partners"], {"abuela": 1})
        self.assertEqual(A.gap(lb)["gap_negotiating"], 10)

    def test_rivals_show_a_page_being_built_and_the_eggs(self):
        now = time.time()
        buy = lambda ref, frm, price: {"ts": now - 30, "type": "settlement", "payload": {
            "parties": ["t18", frm], "price": price, "items": [{"ref": ref, "frm": frm, "to": "t18"}]}}
        feed = [buy(f"CHA-{n:02d}", "abuela", 9) for n in range(2, 11)] + [buy("CHA-01", "t13", 72),
                buy("CHA-11", "picaros", 145),
                {"ts": now - 20, "tick": 1482, "type": "egg.given", "actor": "abuela",
                 "payload": {"team": "t18", "cards": ["LAV-08"], "cash": 0}},
                {"ts": now - 99999, "tick": 9, "type": "egg.given", "payload": {"team": "t01", "cards": ["OLD-01"]}}]
        lb = {"teams": [{"team": "t18", "score": 31, "negotiating": 24, "market": 6, "rank": 1,
                         "pages_complete": 4, "album_filled": 48},
                        {"team": "t10", "score": 30, "negotiating": 23, "market": 10, "rank": 2}]}
        r = A.rivals(feed, lb, {}, now - 3600)
        t18 = r["teams"]["t18"]
        self.assertEqual(t18["page_cards_bought"], {"CHA": 10})  # the epic 11 is off the page
        self.assertEqual(t18["page_cards_from_teams"], [{"ref": "CHA-01", "price": 72, "book": None, "from": "t13"}])
        self.assertEqual((t18["pages_complete"], t18["album_filled"]), (4, 48))
        self.assertEqual(r["eggs"], [{"tick": 1482, "team": "t18", "dealer": "abuela", "cards": ["LAV-08"],
                                      "cash": 0, "given": True}])
        self.assertIn("+50", r["how_to_read"])

    def test_idle_diagnosis(self):
        me = {"cash": 66}
        offers = [{"maker": "t10", "status": "open", "thread": None, "give": {"cash": 40}},
                  {"maker": "t10", "status": "open", "thread": None, "give": {"cash": 11}}]
        decisions = [{"tick": 100, "source": "fallback", "verdict": {"ok": False, "rail": "cash"}}]
        outcomes = [{"kind": "broker_announce", "status": "refused", "response": {"message": "one per 20 ticks"}}]
        d = A.idle(Path("."), me, offers, {"MAL-09": 88}, decisions, outcomes, {"tick": 110})
        self.assertEqual(d["cash_locked_in_bids"], 51)
        self.assertEqual(d["ticks_without_actions_last_20"], 19)
        causes = " | ".join(d["likely_causes"])
        for needle in ("51 P of our 66 P", "MAL-09", "rail vetoes", "refusals", "fallback"):
            self.assertIn(needle, causes)

    def test_llm_health_flags_failing_key(self):
        live = Path(tempfile.mkdtemp())
        now = time.time()
        rows = [{"ts": now - 10, "key": "B", "error": "400 workspace", "error_kind": "dead"} for _ in range(3)]
        rows += [{"ts": now - 10, "key": "A", "usage": {}, "cost_usd": 0.01}]
        (live / "llm.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        h = A.llm_health(live, {"usd": 90, "cap": 100, "by_key": {"B": {"dead": "400 workspace"}}}, now)
        text = " | ".join(h["anomalies"])
        self.assertIn("key B: 3 errors", text)
        self.assertIn("key B is dead", text)
        self.assertIn("90%", text)


class ReserveFromCapsTest(unittest.TestCase):
    def _idle(self, control):
        live = Path(tempfile.mkdtemp())
        if control is not None:
            (live / "control.json").write_text(json.dumps(control))
        return A.idle(live, {"cash": 50}, [], {}, [], [], {"tick": 10})

    def test_nested_caps_reserve_is_the_one_the_brain_sees(self):
        d = self._idle({"caps": {"cash_reserve": 5}})          # how the dashboard stores it
        self.assertEqual((d["cash_reserve"], d["cash_available"]), (5, 45))

    def test_caps_win_over_a_stale_flat_key_like_in_the_bot(self):
        d = self._idle({"cash_reserve": 15, "caps": {"cash_reserve": 5}})
        self.assertEqual(d["cash_reserve"], 5)

    def test_flat_key_and_default_still_work(self):
        self.assertEqual(self._idle({"cash_reserve": 8})["cash_reserve"], 8)
        from bazaar import config
        self.assertEqual(self._idle(None)["cash_reserve"], config.CASH_RESERVE)


class OffersTest(unittest.TestCase):
    me = {"assets": [{"id": 1, "ref": "RET-01", "your_value": 11.0}, {"id": 2, "ref": "MAL-01", "your_value": 13.0}],
          "album": {"pages": [{"set": "RET", "have": 2, "of": 10}, {"set": "MAL", "have": 8, "of": 10}]}}

    def test_offers_to_us_and_unknown(self):
        offers = [{"id": 4167, "maker": "t05", "to": "t10", "status": "open", "thread": None, "venue": "rastro",
                   "give": {"cash": 20}, "want": {"types": ["card:RET-01"]}},
                  {"id": 4117, "maker": "t10", "status": "open", "thread": None, "venue": "v10",
                   "give": {"assets": [{"ref": "RET-06"}]}, "want": {"cash": 55}},
                  {"id": 4033, "maker": "t10", "status": "open", "thread": None, "venue": "rastro",
                   "give": {"assets": [{"ref": "MAL-02"}]}, "want": {"types": ["card:RET-04"]}}]
        to_us = A.offers_to_us(offers, self.me, {"v10": "t05"})
        self.assertEqual(len(to_us), 1)
        o = to_us[0]
        self.assertTrue(o["ally"])
        self.assertTrue(o["last_copy"])
        self.assertEqual(o["value_gain_cash_only"], 9.0)
        self.assertEqual(o["page_completion"], {"RET": "2/10"})
        live = Path(tempfile.mkdtemp())
        (live / "outcomes.jsonl").write_text(json.dumps({"kind": "post_offer", "response": {"id": 4033}}) + "\n")
        self.assertEqual([x["offer"] for x in A.unknown_offers(offers, live)], [4117])

    def test_keep_one_exception_and_rail(self):
        from bazaar.brain import strategy as S
        from bazaar.core import rails
        from bazaar.core.types import Action
        S.path().write_text(json.dumps({"updated": time.time(), "plan": {"accept_offers": [4167]}}))
        try:
            sit = {"me": {**self.me, "id": "t10"}, "my_offers": []}
            self.assertTrue(S.keep_one_exception(sit, "RET-01", 4167))
            self.assertFalse(S.keep_one_exception(sit, "RET-01", 999))         # not approved
            self.assertFalse(S.keep_one_exception(sit, "MAL-01", 4167))        # MAL page 8/10: keep it
            a = Action(kind="accept_offer", params={"offer": 4167, "give": {"assets": [1]}, "want": {"cash": 20}},
                       domain="market")
            b = Action(kind="accept_offer", params={"offer": 5000, "give": {"assets": [1]}, "want": {"cash": 20}},
                       domain="market")
            self.assertTrue(rails.rail_cards(a, sit, None).ok)
            self.assertFalse(rails.rail_cards(b, sit, None).ok)
        finally:
            S.path().unlink()


if __name__ == "__main__":
    unittest.main()
