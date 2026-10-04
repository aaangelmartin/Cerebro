"""What the security review found in the price, the limits, the agent queue and the search, each as it was done."""
import tempfile
import time
import unittest
from pathlib import Path

from bazaar.plaza import agentq as Q
from bazaar.plaza import deals as D
from bazaar.plaza import matcher as M
from bazaar.plaza import private, quotes
from bazaar.plaza.store import PlazaError
from bazaar.plaza.tests.test_deals_api import listed, settled
from bazaar.plaza.tests.test_matcher import CAT, agent, sheets


class Vaulted(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.v = private.Vault(Path(self.dir.name) / "p")
        self.q = quotes.Quoter(self.v)

    def tearDown(self):
        self.dir.cleanup()


class LimitLeakTest(Vaulted):
    def found(self, max_, asks):
        """Which public asks of t01 get a match with t02, whose private max is `max_`? One fresh board per run."""
        with tempfile.TemporaryDirectory() as d:
            v = private.Vault(Path(d) / "p")
            v.data = {"t02": {"SAL-09": {"max": max_}}}
            q, out = quotes.Quoter(v), []
            for i, x in enumerate(asks):
                sh = sheets(agent("t01", spares=["SAL-09"], sale=[{"ref": "SAL-09", "price": x, "source": "agent"}]),
                            agent("t02", wants=["SAL-09"]))
                ms = M.find(sh, CAT, quote=q.at(100 + 40 * i).quote)
                out.append((bool(ms), ms[0]["price"] if ms else None))
            return out

    def test_a_public_ask_cannot_search_for_a_private_max(self):
        """The review's search: publish an ask, watch whether the match appears, halve the interval. Whatever the
        victim's max is, the answers are the same: the ask is never held against it."""
        asks = [1000, 500, 250, 125, 187, 156, 140, 132, 136, 138, 137]
        self.assertEqual(self.found(137, asks), self.found(60, asks))
        self.assertEqual(self.found(137, asks), self.found(1999, asks))

    def test_the_price_is_never_a_limit_and_always_inside(self):
        for lo, hi in [(120, 150), (146, 150), (147, 150), (60, 62), (5, 9), (18, 23), (100, 2000), (40, 45)]:
            for ref in (1, lo, hi, (lo + hi) // 2, 5000):
                self.v.data = {"t01": {"SAL-09": {"min": lo}}, "t02": {"SAL-09": {"max": hi}}}
                p = self.q.quote("t01", "t02", "SAL-09", ref, 1)["price"]
                self.assertTrue(lo < p < hi, (lo, hi, ref, p))
        for lo, hi in [(150, 150), (149, 150), (151, 150)]:          # no inside: no price
            self.v.data = {"t01": {"SAL-09": {"min": lo}}, "t02": {"SAL-09": {"max": hi}}}
            self.assertIsNone(quotes.Quoter(self.v).quote("t01", "t02", "SAL-09", 100, 1)["price"])

    def test_a_reference_outside_the_overlap_does_not_push_the_price_to_an_end(self):
        """The second cold test: book 180, the buyer's max 170, price 165: one grid step under the max."""
        near = 0
        for i in range(80):
            with tempfile.TemporaryDirectory() as d:
                v = private.Vault(Path(d) / "p")
                q = quotes.Quoter(v)
                for lo, hi, ref in ((55, 170, 180), (55, 170, 20), (100, 400, 450), (100, 400, 10)):
                    v.data = {"t01": {"SAL-09": {"min": lo}}, "t02": {"SAL-09": {"max": hi}}}
                    p = q.quote("t01", "t02", "SAL-09", ref, 1)["price"]
                    self.assertTrue(lo + (hi - lo) // 4 <= p <= hi - (hi - lo) // 4, (lo, hi, ref, p))
                    near += min(p - lo, hi - p) <= 5
        self.assertEqual(near, 0)
        v = private.Vault(Path(self.dir.name) / "narrow")            # a minimal overlap: inside, as far as it goes
        v.data = {"t01": {"SAL-09": {"min": 166}}, "t02": {"SAL-09": {"max": 170}}}
        self.assertIn(quotes.Quoter(v).quote("t01", "t02", "SAL-09", 180, 1)["price"], (167, 168, 169))

    def test_the_grid_rounds_inwards(self):
        """The cold test: book 180, the buyer's max 150. 146 to 149 used to round up to 150, the max itself."""
        for lo in range(100, 147):
            p = M.inside(lo, 150, 180, 1)
            self.assertTrue(lo < p < 150, (lo, p))
        self.assertEqual(M.inside(100, 150, 180, 1), 145)

    def test_moving_my_limit_does_not_solve_for_yours(self):
        """Two prices seen with two limits of my own gave the other limit by a straight line (120 and 130 -> 136
        for a true 137). The margin now changes with either limit: over many vaults the line misses."""
        errors = []
        for i in range(60):
            with tempfile.TemporaryDirectory() as d:
                v = private.Vault(Path(d) / "p")
                q = quotes.Quoter(v)
                seen = []
                for lo in (20, 60):
                    v.data = {"t01": {"SAL-09": {"min": lo}}, "t02": {"SAL-09": {"max": 137}}}
                    seen.append((lo, q.quote("t01", "t02", "SAL-09", 5000, 1)["price"]))   # p = hi - s * (hi - lo)
                (l1, p1), (l2, p2) = seen
                if p1 != p2 and (p1 - p2) != (l1 - l2):
                    s = (p1 - p2) / ((p1 - p2) - (l1 - l2))                                # the old attack's algebra
                    errors.append(abs((p1 - s * l1) / (1 - s) - 137) if s != 1 else 999)
                else:
                    errors.append(999)
        self.assertGreater(sum(e > 5 for e in errors), 40, errors)

    def test_a_public_price_is_followed_once_per_hold(self):
        self.assertEqual(self.q.at(10).quote("t01", "t02", "SAL-09", 70, 1, ask=90)["price"], 90)
        self.assertEqual(self.q.at(12).quote("t01", "t02", "SAL-09", 70, 1, ask=60)["price"], 90)   # too soon: 90 stays
        self.assertEqual(self.q.at(12).quote("t01", "t02", "SAL-09", 70, 1, ask=None)["price"], 90)  # nor by clearing it
        self.assertEqual(self.q.at(10 + quotes.HOLD_TICKS).quote("t01", "t02", "SAL-09", 70, 1, ask=80)["price"], 80)

    def test_a_value_refusal_is_kept_too(self):
        self.v.data = {"t01": {"SAL-09": {"value": 90}}, "t02": {"SAL-09": {"value": 80}}}
        self.assertIs(self.q.at(5).quote("t01", "t02", "SAL-09", 70, 1)["value"], False)
        self.v.data["t01"]["SAL-09"]["value"] = 10                    # walks its value down to find the buyer's
        self.assertIsNone(self.q.at(6).quote("t01", "t02", "SAL-09", 70, 1)["price"])


class CooldownTest(Vaulted):
    def test_clearing_a_limit_is_no_way_round_the_cooldown(self):
        self.v.put("t01", "SAL-09", {"min": 50}, tick=100)             # the first time: free
        self.v.put("t01", "SAL-09", {"min": 60}, tick=101)             # one move
        with self.assertRaises(PlazaError):
            self.v.put("t01", "SAL-09", {"min": 70}, tick=102)
        self.v.put("t01", "SAL-09", {"min": None}, tick=103)           # forgetting is always allowed
        with self.assertRaises(PlazaError) as e:
            self.v.put("t01", "SAL-09", {"min": 70}, tick=104)         # and setting it again is a move like any other
        self.assertEqual((e.exception.status, e.exception.code), (429, "slow_down"))
        self.v.put("t01", "SAL-09", {"min": 70}, tick=103 + private.COOL_TICKS)
        self.v.put("t01", "SAL-09", {"max": 90}, tick=104 + private.COOL_TICKS)   # another field: its own clock

    def test_a_value_moves_once_in_twenty_ticks_too(self):
        self.v.put("t01", "SAL-09", {"value": 50}, tick=100)
        self.v.put("t01", "SAL-09", {"value": 60}, tick=101)
        with self.assertRaises(PlazaError):
            self.v.put("t01", "SAL-09", {"value": 70}, tick=102)
        self.v.put("t01", "SAL-09", {"value": 60}, tick=102)           # the same number again: nothing moved


def match(**kw):
    m = {"id": "m-0123456789", "kind": "sale", "seller": "t01", "buyer": "t02", "ref": "SAL-09", "price": 100,
         "suggested": 100, "state": "proposed", "agreed": [], "offer": None, "venue": "v07",
         "recipe": M.recipe("t01", "t02", "SAL-09", 100)}
    m.update(kw)
    return m


class AutoModeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.q = Q.AgentQ(Path(self.dir.name) / "q.json")

    def tearDown(self):
        self.dir.cleanup()

    def types(self, team, m, limit):
        """The buyer's max or the seller's min is `limit`; None: it set none."""
        def within(ref, role, price):
            return None if limit is None else (price <= limit if role == "buyer" else price >= limit)
        return [a["type"] for a in self.q.build(team, [m], within, time.time(), 1)["actions"]]

    def test_auto_goes_ahead_only_at_the_markets_price_inside_its_own_limit(self):
        self.assertEqual(self.types("t02", match(), 180), ["post_offer"])
        self.assertEqual(self.types("t01", match(), 60), ["agree"])

    def test_a_price_the_other_side_chose_is_the_agents_call(self):
        """The review: the seller counters downwards from 400 and the buyer's queue walks to its max of 180."""
        for price in (400, 200, 181, 180, 150):
            m = match(price=price, price_by="t01", agreed=["t01"], id=f"m-{price:010d}")
            self.assertEqual(self.types("t02", m, 180), ["decide"], price)
        m = match(price=150, price_by="t02", agreed=["t02"])           # its own counter: it stands by it
        self.assertEqual(self.types("t02", m, 180), ["post_offer"])

    def test_no_limit_of_its_own_is_not_a_yes(self):
        self.assertEqual(self.types("t02", match(price=2000, suggested=2000), None), ["decide"])
        self.assertEqual(self.types("t01", match(), None), ["decide"])
        self.assertEqual(self.types("t02", match(agreed=["t02"]), None), ["post_offer"])   # once the agent said yes

    def test_an_offer_at_another_price_waits_for_the_agent(self):
        m = match(state="offer_on_v07", offer=7, offer_maker="t02", price=40, price_by="t02", agreed=["t02"])
        self.assertEqual(self.types("t01", m, 30), ["decide"])
        m = match(state="accepted", offer=7, offer_maker="t02", price=40, price_by="t02", agreed=["t02", "t01"])
        self.assertEqual(self.types("t01", m, 30), ["accept_offer"])   # it said yes on the thread: now the game


class DealsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = D.Deals(Path(self.dir.name) / "matches.json")
        self.cands = M.find(sheets(agent("t01", spares=["SAL-09"]), agent("t02", wants=["SAL-09"])), CAT)
        self.d.sync(self.cands, 10, [])
        self.mid = self.cands[0]["id"]
        self.price = self.cands[0]["price"]

    def tearDown(self):
        self.dir.cleanup()

    def rec(self):
        return self.d.get(self.mid)

    def test_an_offer_at_another_price_is_the_makers_and_voids_the_others_word(self):
        self.d.message(self.mid, "t01", True, {"action": "accept"})
        self.d.sync(self.cands, 11, [listed(11, "t02", "t01", "SAL-09", self.price - 10)])
        r = self.rec()
        self.assertEqual((r["state"], r["price"], r["price_by"], r["agreed"]), ("offer_on_v07", self.price - 10, "t02", []))

    def test_an_offer_under_the_floor_is_not_the_match(self):
        self.d.sync(self.cands, 11, [listed(11, "t02", "t01", "SAL-09", 1)])
        self.assertEqual((self.rec()["state"], self.rec()["price"]), ("proposed", self.price))
        self.assertEqual(self.d.notes[-1]["kind"], "below_floor")
        with self.assertRaises(PlazaError) as e:
            self.d.report_offer(self.mid, "t02", 9, {"venue": "v07", "maker": "t02", "to": "t01", "ref": "SAL-09", "price": 1})
        self.assertEqual(e.exception.code, "below_floor")

    def test_the_same_card_going_the_other_way_is_not_the_match(self):
        back = {**settled(12, "t01", "t02", "SAL-09", 50, "v07"), "moves": [{"ref": "SAL-09", "from": "t02", "to": "t01"}]}
        self.d.sync(self.cands, 12, [back])
        self.assertEqual(self.rec()["state"], "proposed")
        right = {**settled(13, "t01", "t02", "SAL-09", 50, "v07"), "moves": [{"ref": "SAL-09", "from": "t01", "to": "t02"}]}
        self.d.sync(self.cands, 13, [back, right])
        self.assertEqual(self.rec()["state"], "settled")

    def test_one_teams_notes_or_offer_ids_do_not_hold_the_others_card(self):
        self.d.message(self.mid, "t02", True, {"text": "thinking about it"})
        self.d.report_offer(self.mid, "t02", 5001, None)
        self.d.sync([], 12, [])                                       # the sheets no longer support the match
        with self.assertRaises(PlazaError):
            self.rec()

    def test_talk_alone_does_not_live_for_ever(self):
        for tick in range(20, D.PROPOSAL_HARD + 30, 50):               # a counter every 50 ticks, never an offer
            if self.rec()["state"] != "proposed":
                break
            self.d.sync(self.cands, tick, [])
            self.d.message(self.mid, "t01" if tick % 100 else "t02", True, {"action": "counter", "price": 60 + tick % 7})
        self.d.sync(self.cands, D.PROPOSAL_HARD + 40, [])
        self.assertEqual(self.rec()["state"], "expired")

    def test_offer_ids_the_feed_never_shows_run_out(self):
        for i in range(D.MAX_REPORTS):
            self.d.report_offer(self.mid, "t02", 6000 + i, None)
        self.d.report_offer(self.mid, "t02", 6000 + D.MAX_REPORTS - 1, None)       # the same id again: no count
        with self.assertRaises(PlazaError) as e:
            self.d.report_offer(self.mid, "t02", 7000, None)
        self.assertEqual(e.exception.status, 429)

    def test_the_same_accept_in_the_same_state_writes_once(self):
        self.assertIsNone(self.d.repeated(self.mid, "t01", {"action": "accept"}))
        self.d.message(self.mid, "t01", True, {"action": "accept"})
        self.assertIsNotNone(self.d.repeated(self.mid, "t01", {"action": "accept"}))   # proposed: said already
        self.d.sync(self.cands, 11, [listed(11, "t02", "t01", "SAL-09", self.price)])
        self.assertIsNone(self.d.repeated(self.mid, "t01", {"action": "accept"}))      # a new state: the confirm
        self.d.message(self.mid, "t01", True, {"action": "accept"})
        self.assertIsNotNone(self.d.repeated(self.mid, "t01", {"action": "accept"}))
        self.assertEqual(len(self.rec()["messages"]), 2)


class SearchTest(Vaulted):
    def big(self, teams=17, wants=60, holds=120):
        refs = [f"{s}-{n:02d}" for s in ("LAV", "MAL", "LAT", "SAL", "RET", "CHA") for n in range(1, 31)]
        cat = {r: {"name": r, "rarity": "common", "book": 10} for r in refs}
        rows = []
        for i in range(teams):
            mine = [refs[(i * 7 + k) % len(refs)] for k in range(holds)]
            rows.append(agent(f"t{i + 20}", wants=[refs[(i * 7 + holds + k) % len(refs)] for k in range(wants)],
                              spares=mine[:holds // 2], sale=mine[holds // 2:]))
        return sheets(*rows), cat

    def test_the_largest_sheets_the_contract_allows_do_not_hold_the_board(self):
        sh, cat = self.big()
        t0 = time.monotonic()
        ms = M.find(sh, cat, quote=self.q.quote)
        took = time.monotonic() - t0
        self.assertLess(took, 1.0, took)
        self.assertTrue(ms)
        self.assertLessEqual(sum(m["kind"] == "triangle" for m in ms), M.MAX_TRIANGLES)
        t0 = time.monotonic()
        M.find(sh, cat)                                               # what the broker calls: no vault
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_a_swap_a_team_said_it_loses_on_is_not_proposed(self):
        sh = sheets(agent("t01", spares=["LAT-03"], wants=["RET-03"]), agent("t02", spares=["RET-03"], wants=["LAT-03"]))
        swaps = lambda: [m["kind"] for m in M.find(sh, CAT, quote=self.q.quote) if m["kind"] == "swap"]   # noqa: E731
        self.assertEqual(swaps(), ["swap"])
        self.v.data = {"t01": {"LAT-03": {"value": 30}, "RET-03": {"value": 10}}}      # t01 gives 30 to get 10
        self.assertEqual(swaps(), [])
        self.v.data = {"t01": {"LAT-03": {"value": 5}, "RET-03": {"value": 10}}}
        self.assertEqual(swaps(), ["swap"])

if __name__ == "__main__":
    unittest.main()
