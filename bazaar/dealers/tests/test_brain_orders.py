"""The brain's dealer_orders: the dealers domain opens the ordered thread first, keeps the brain's bounds and
tells the brain why an order could not start."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bazaar.brain import strategy as S
from bazaar.dealers.domain import DealersDomain
from bazaar.dealers.evaluate import FRIDAY_PERSONAS, SCENARIOS, make_catalog, make_ctx, make_sit
from bazaar.dealers.profiles import ProfileStore
from bazaar.dealers.simulator import DealerWorld

PILAR = {"id": "pilar", "name": "Doña Pilar", "kind": "collector", "level": 3, "status": "active",
         "open_to_all": True, "traits": {"patience": 0.5, "generosity": 0.4, "shrewdness": 0.6},
         "menu": {"buys": [{"rarity": "uncommon", "sets": ["SAL", "RET"]},
                           {"rarity": "uncommon", "sets": "released"}], "deals_per_team_per_hour": 6}}


def domain(orders) -> tuple[DealersDomain, list]:
    dom = DealersDomain(store=ProfileStore(Path(tempfile.mkdtemp()) / "m.json"), catalog=make_catalog(), use_llm=False)
    dom._brain_orders = lambda: list(orders)
    notes = []
    dom._note_order = lambda o, status, detail="", tick=None, **kw: notes.append((o["ref"], status, detail))
    return dom, notes


def sit(assets, dealers=(PILAR,), cash=20, offers=()):
    return SimpleNamespace(tick=5, me={"id": "t10", "cash": cash, "unlocked": [d["id"] for d in dealers],
                                       "affinity": {"LAV": 1.6, "MAL": 1.3, "RET": 1.1, "SAL": 0.9, "LAT": 0.5},
                                       "assets": assets},
                           threads=[], my_offers=list(offers), dealers=list(dealers),
                           limits={"max_open_threads_per_team": 6}, feed_new=[], closed_threads=[])


def order(**kw):
    return {"dealer": "pilar", "action": "sell", "ref": "SAL-08", "open": 30, "bound": 25, "max_messages": 4,
            "why": "", **kw}


SAL08 = {"id": 7, "kind": "card", "ref": "SAL-08", "rarity": "uncommon", "set": "SAL", "your_value": 22.5}


class SanitizeTest(unittest.TestCase):
    def test_orders_are_cleaned(self):
        out = S._dealer_orders([
            {"dealer": "Pilar", "action": "sell", "ref": "sal-08", "open": 30, "floor_or_cap": 25, "max_messages": 4},
            {"dealer": "chato", "action": "buy", "ref": "MAL-09", "open": 72, "cap": 88},
            {"dealer": "pilar", "action": "sell", "ref": "SAL-08", "floor": 20},          # duplicate
            {"dealer": "x y", "action": "sell", "ref": "SAL-08", "floor": 20},             # bad dealer
            {"dealer": "pilar", "action": "gift", "ref": "SAL-08", "floor": 20},           # bad action
            {"dealer": "pilar", "action": "sell", "ref": "SAL-01"}])                       # no bound
        self.assertEqual([(o["dealer"], o["action"], o["ref"], o["open"], o["bound"], o["max_messages"]) for o in out],
                         [("pilar", "sell", "SAL-08", 30, 25, 4), ("chato", "buy", "MAL-09", 72, 88, 4)])
        self.assertEqual(S.sanitize({"dealer_orders": "nope"})["dealer_orders"], [])

    def test_outcome_text_mentions_orders(self):
        with tempfile.TemporaryDirectory() as d:
            S.record_post({"kind": "dealer_order", "tick": 9, "dealer": "pilar", "action": "sell", "ref": "SAL-08",
                           "status": "skipped", "detail": "we do not hold SAL-08"}, Path(d))
            self.assertIn("dealer order sell SAL-08 with pilar -> skipped: we do not hold SAL-08",
                          S.post_outcomes_text(Path(d)))


class OrderOpensTest(unittest.TestCase):
    def test_order_opens_even_when_the_learned_range_says_no(self):
        # live case: after two Pilar deals her learned top (~25) fell under our floor, so the code never opened it
        dom, _ = domain([])
        for i in range(4):
            dom.store.learn_thread("pilar", "sell:uncommon:loved", 22, [22, 23, 24], [30, 28], True, False)
        self.assertFalse([a for a in dom.fallback(sit([dict(SAL08)]), make_ctx(5)) if a.kind == "open_thread"])
        dom, notes = domain([order()])
        for i in range(4):
            dom.store.learn_thread("pilar", "sell:uncommon:loved", 22, [22, 23, 24], [30, 28], True, False)
        opens = [a for a in dom.fallback(sit([dict(SAL08)]), make_ctx(5)) if a.kind == "open_thread"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(opens[0].params, {"with": "pilar", "topic": {"sell": {"assets": [7]}}})
        self.assertIn("brain order", opens[0].reason)
        self.assertEqual(opens[0].expected["limit"], 25)          # max(order floor 25, value + margin 25)
        self.assertEqual(notes, [])

    def test_floor_is_never_below_our_value_plus_margin(self):
        dom, _ = domain([order(bound=10)])
        opens = [a for a in dom.fallback(sit([dict(SAL08)]), make_ctx(5)) if a.kind == "open_thread"]
        self.assertEqual(opens[0].expected["limit"], 25)

    def test_order_beats_the_domains_own_candidate_for_that_dealer(self):
        spare = [{"id": 1, "kind": "card", "ref": "SAL-07", "rarity": "uncommon", "set": "SAL", "your_value": 2},
                 {"id": 2, "kind": "card", "ref": "SAL-07", "rarity": "uncommon", "set": "SAL", "your_value": 2},
                 dict(SAL08)]
        dom, _ = domain([order()])
        plan = dom._prepare(sit(spare), make_ctx(5))
        self.assertEqual([c.id for c in plan.candidates if c.dealer == "pilar"], ["o1"])
        opens = [a for a in dom._with_orders(plan, []) if a.kind == "open_thread"]
        self.assertEqual(opens[0].params["topic"], {"sell": {"assets": [7]}})

    def test_skips_tell_the_brain_why(self):
        cases = [
            ([], order(), "we do not hold SAL-08"),
            ([dict(SAL08)], order(dealer="nadie"), "dealer nadie is not available"),
            ([{"id": 3, "kind": "card", "ref": "LAV-07", "rarity": "uncommon", "set": "LAV", "your_value": 40}],
             order(ref="LAV-07"), "last copy of a set we collect"),
            ([{"id": 4, "kind": "card", "ref": "SAL-01", "rarity": "common", "set": "SAL", "your_value": 9}],
             order(ref="SAL-01"), "pilar does not buy common SAL"),
        ]
        for assets, o, text in cases:
            dom, notes = domain([o])
            acts = dom.fallback(sit(assets), make_ctx(5))
            self.assertFalse([a for a in acts if a.kind == "open_thread" and "brain order" in a.reason], text)
            self.assertTrue(notes and notes[0][1] == "skipped" and text in notes[0][2], (text, notes))

    def test_card_tied_to_an_open_offer_is_reported(self):
        dom, notes = domain([order()])
        offers = [{"id": 99, "maker": "t10", "give": {"assets": [dict(SAL08)]}, "want": {"cash": 30}}]
        acts = dom.fallback(sit([dict(SAL08)], offers=offers), make_ctx(5))
        self.assertFalse([a for a in acts if a.kind == "open_thread"])
        self.assertIn("tied to one of our open offers", notes[0][2])

    # --- the spare copy of a set we collect (outbox request code-b424c250) ----------------------------
    LAV07 = [{"id": 3, "kind": "card", "ref": "LAV-07", "rarity": "uncommon", "set": "LAV", "your_value": 40},
             {"id": 4, "kind": "card", "ref": "LAV-07", "rarity": "uncommon", "set": "LAV", "your_value": 6}]

    def _opens(self, acts):
        return [a for a in acts if a.kind == "open_thread" and "brain order" in a.reason]

    def test_two_copies_one_is_sellable(self):
        dom, notes = domain([order(ref="LAV-07", bound=45)])
        acts = dom.fallback(sit([dict(a) for a in self.LAV07]), make_ctx(5))
        self.assertEqual(len(self._opens(acts)), 1)
        self.assertEqual(notes, [])

    def test_two_copies_with_one_in_our_own_offer_frees_it_first(self):
        dom, notes = domain([order(ref="LAV-07", bound=45)])
        offers = [{"id": 99, "maker": "t10", "give": {"assets": [dict(self.LAV07[1])]}, "want": {"cash": 30}}]
        with mock.patch.object(DealersDomain, "_may_withdraw", staticmethod(lambda offer, control: True)):
            acts = dom.fallback(sit([dict(a) for a in self.LAV07], offers=offers), make_ctx(5))
        self.assertFalse(self._opens(acts))                      # never both copies out at once
        cancels = [a for a in acts if a.kind == "cancel_offer"]
        self.assertEqual([a.params for a in cancels], [{"offer": 99}])
        self.assertEqual(notes[0][1], "waiting")
        self.assertIn("our offer #99", notes[0][2])

    def test_two_copies_with_one_in_a_protected_or_hand_posted_offer_stays_blocked(self):
        dom, notes = domain([order(ref="LAV-07", bound=45)])
        offers = [{"id": 99, "maker": "t10", "give": {"assets": [dict(self.LAV07[1])]}, "want": {"cash": 30}}]
        with mock.patch.object(DealersDomain, "_may_withdraw", staticmethod(lambda offer, control: False)):
            acts = dom.fallback(sit([dict(a) for a in self.LAV07], offers=offers), make_ctx(5))
        self.assertFalse(self._opens(acts))
        self.assertFalse([a for a in acts if a.kind == "cancel_offer"])
        self.assertEqual(notes[0][1], "skipped")
        self.assertIn("promised in offer #99", notes[0][2])

    def test_may_withdraw_only_bot_posted_and_unprotected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "bot_posted_offers.json").write_text('{"since_tick": 1, "ids": ["99"]}')
            with mock.patch("bazaar.dealers.domain.config.LIVE", Path(d)):
                self.assertTrue(DealersDomain._may_withdraw({"id": 99}, {}))
                self.assertFalse(DealersDomain._may_withdraw({"id": 98}, {}))                      # posted by hand
                self.assertFalse(DealersDomain._may_withdraw({"id": 99}, {"protected_offers": [99]}))

    def test_buy_order_respects_value_and_avoided_sets(self):
        chato = next(p for p in FRIDAY_PERSONAS if p["id"] == "chato")
        o = {"dealer": "chato", "action": "buy", "ref": "MAL-09", "open": 72, "bound": 200, "max_messages": 4}
        dom, _ = domain([o])
        opens = [a for a in dom.fallback(sit([], dealers=[chato], cash=400), make_ctx(5)) if a.kind == "open_thread"]
        self.assertEqual(opens[0].params["topic"], {"buy": {"card": "MAL-09"}})
        self.assertLess(opens[0].expected["limit"], opens[0].expected["value"])      # never the brain's 200
        dom, notes = domain([dict(o, ref="RET-09")])
        ctx = make_ctx(5)
        ctx.control = {"avoid_buy_sets": ["RET"]}
        acts = dom.fallback(sit([], dealers=[chato], cash=400), ctx)
        self.assertFalse([a for a in acts if a.kind == "open_thread" and "brain order" in a.reason])
        self.assertIn("a set we avoid buying", notes[0][2])

    def test_arbitrage_order_is_capped_by_the_resale_not_our_value(self):
        # a second MAL-10 is worth little to us, but another team bids for it: the job's cap is the limit
        chato = next(p for p in FRIDAY_PERSONAS if p["id"] == "chato")
        mal10 = {"id": 5, "kind": "card", "ref": "MAL-10", "rarity": "rare", "set": "MAL", "your_value": 91.0}
        o = {"dealer": "chato", "action": "buy", "ref": "MAL-10", "open": 44, "bound": 69, "max_messages": 5}
        dom, _ = domain([o])
        plain = [a for a in dom.fallback(sit([dict(mal10)], dealers=[chato], cash=400), make_ctx(5))
                 if a.kind == "open_thread" and a.params["topic"] == {"buy": {"card": "MAL-10"}}]
        self.assertTrue(not plain or plain[0].expected["limit"] < 69)                # value-bound without the tag
        dom, _ = domain([dict(o, arbitrage=True)])
        opens = [a for a in dom.fallback(sit([dict(mal10)], dealers=[chato], cash=400), make_ctx(5))
                 if a.kind == "open_thread"]
        self.assertEqual(opens[0].params["topic"], {"buy": {"card": "MAL-10"}})
        self.assertEqual(opens[0].expected["limit"], 69)

    def test_an_order_that_ended_is_not_reopened_with_the_same_bound(self):
        dom, _ = domain([order()])
        dom._order_done[("pilar", "sell", "SAL-08")] = 25
        brain = lambda acts: [a for a in acts if a.kind == "open_thread" and "brain order" in a.reason]  # noqa: E731
        self.assertFalse(brain(dom.fallback(sit([dict(SAL08)]), make_ctx(5))))
        dom._brain_orders = lambda: [order(bound=27)]              # the brain re-planned it
        self.assertTrue(brain(dom.fallback(sit([dict(SAL08)]), make_ctx(5))))


class OrderBoundsInThreadTest(unittest.TestCase):
    def test_sell_thread_uses_the_brains_floor(self):
        scen = SCENARIOS[4]                                        # chato buys our spare SAL-07 (worth 5.6)
        w = DealerWorld(seed=1)
        w.open(scen.dealer, scen.topic, scen.kind, scen.item_type, asset_ids=[901])
        w.advance()
        dom, _ = domain([])
        base = dom._prepare(make_sit(w, scen), make_ctx(w.tick)).infos[0].limit
        dom, _ = domain([{"dealer": "chato", "action": "sell", "ref": "SAL-07", "open": 20, "bound": base + 6,
                          "max_messages": 4}])
        info = dom._prepare(make_sit(w, scen), make_ctx(w.tick)).infos[0]
        self.assertEqual(info.limit, base + 6)
        self.assertFalse(info.force_close)                         # not closed to keep the spare for a higher dealer

    def test_opened_order_is_reported_once(self):
        dom = DealersDomain(store=ProfileStore(Path(tempfile.mkdtemp()) / "m.json"), catalog=make_catalog(),
                            use_llm=False)
        dom._brain_orders = lambda: [order()]
        rows = []
        with mock.patch.object(S, "record_post", lambda row, live=None: rows.append(row)):
            a = [x for x in dom.fallback(sit([dict(SAL08)]), make_ctx(5)) if x.kind == "open_thread"][0]
            out = SimpleNamespace(action_id=a.id, tick=5, status="sent", response={})
            dom.observe(out)
            dom._note_order(order(), "opened", "", 5)              # same news twice: one line
        self.assertEqual([(r["kind"], r["ref"], r["status"]) for r in rows], [("dealer_order", "SAL-08", "opened")])
        self.assertEqual(dom._order_bound[("pilar", "sell", "SAL-08")], 25)


if __name__ == "__main__":
    unittest.main()
