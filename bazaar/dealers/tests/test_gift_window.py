"""The gift window: Abuela gives a card every 240 ticks in her answer to our first priced message of a thread.
The bot opens a thread with her by itself once the window is open, once, and names a price before anything else."""
from __future__ import annotations

import json
import unittest

from bazaar.core.types import Outcome
from bazaar.dealers import gifts
from bazaar.dealers.tests import test_card_switch as S
from bazaar.dealers.tests import test_domain as T

SIT, CTX = T.AuditFixes().sit, T.AuditFixes().ctx
SPARES = [{"id": 1, "kind": "card", "ref": "LAT-01", "rarity": "common", "set": "LAT", "your_value": 5.0},
          {"id": 2, "kind": "card", "ref": "LAT-01", "rarity": "common", "set": "LAT", "your_value": 5.0}]


def domain(last_gift=100):
    dom = T.domain()
    dom._brain_orders = lambda: []
    if last_gift is not None:
        gifts.record(dom.store.data, "abuela", last_gift, ["LAV-05"])
    return dom


def opens(dom, tick, control=None, threads=()):
    ctx = CTX(tick)
    ctx.control = control or {}
    # cash 60 leaves nothing to spend in this fixture: no deal with Abuela is worth opening on its own
    out = dom.fallback(SIT(tick=tick, cash=60, assets=[dict(a) for a in SPARES], threads=list(threads)), ctx)
    return [a for a in out if a.kind == "open_thread" and a.params.get("with") == "abuela"], out


class Window(unittest.TestCase):
    def test_closed_window_opens_nothing(self):
        self.assertEqual(opens(domain(), 339)[0], [])

    def test_open_window_opens_one_thread_and_only_once(self):
        dom = domain()
        first, _ = opens(dom, 340)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].params["topic"], {"sell": {"assets": [1]}})
        dom.observe(Outcome(action_id=first[0].id, tick=340, status="sent", response={}))
        self.assertEqual(gifts.tries(dom.store.data, "abuela"), [{"tick": 340, "item": "LAT-01"}])
        self.assertEqual(opens(dom, 341)[0], [])                       # no second thread right behind the first
        self.assertEqual(opens(dom, 340 + gifts.RETRY_TICKS)[0], [])   # ...and the same card is not offered twice

    def test_no_gift_ever_means_the_window_is_open(self):
        self.assertEqual(len(opens(domain(last_gift=None), 5)[0]), 1)

    def test_tries_are_capped(self):
        dom = domain()
        for i in range(gifts.MAX_TRIES):
            gifts.note_try(dom.store.data, "abuela", 340 + 10 * i, f"X-{i}")
        self.assertEqual(opens(dom, 500)[0], [])

    def test_a_gift_restarts_the_clock(self):
        dom = domain()
        gifts.note_try(dom.store.data, "abuela", 340, "LAT-01")
        ev = {"id": 9, "tick": 342, "type": "gift.given", "actor": "abuela",
              "payload": {"team": "t10", "cards": ["SAL-08"], "cash": 0, "packs": []}}
        other = {"id": 8, "tick": 341, "type": "gift.given", "actor": "abuela", "payload": {"team": "t07", "cards": ["X"]}}
        s = SIT(tick=343, cash=60, assets=[dict(a) for a in SPARES])
        s.me["id"] = "t10"
        s.feed_new = [other, ev]
        self.assertEqual([a for a in dom.fallback(s, CTX(343)) if a.kind == "open_thread"
                          and a.params.get("with") == "abuela"], [])
        g = dom.store.data["gifts"]["abuela"]
        self.assertEqual((g["last_tick"], g["cards"], g["tries"], g["count"]), (342, ["SAL-08"], [], 2))
        self.assertFalse(gifts.window_open(dom.store.data, "abuela", 342 + 239))
        self.assertTrue(gifts.window_open(dom.store.data, "abuela", 342 + 240))
        self.assertTrue(gifts.window_open(dom.store.data, "abuela", 3))          # a new day's clock

    def test_a_manual_thread_is_left_alone(self):
        th = S.thread([("d", 339, 27, S.CARD)])
        mine, out = opens(domain(), 340, control={"manual_threads": [10]}, threads=[th])
        self.assertEqual(mine, [])
        self.assertEqual([a for a in out if a.kind in ("thread_message", "close_thread", "accept_offer")], [])

    def test_a_deal_worth_opening_serves_as_the_gift_thread(self):
        dom = domain()
        plan = dom._prepare(SIT(tick=340, cash=400), CTX(340))
        own = [c for c in plan.candidates if c.dealer == "abuela"]
        self.assertTrue(own and own[0].id in plan.forced and not own[0].id.startswith("g"))
        kept = dom._with_orders(plan, [])                              # Claude picked nothing: it opens anyway
        self.assertEqual([a.params["with"] for a in kept if a.kind == "open_thread"], ["abuela"])


class FirstBid(unittest.TestCase):
    def test_the_code_names_a_price_before_claude_may_close(self):
        dom = domain()
        th = S.thread([("d", 340, 27, S.CARD)])
        plan = dom._prepare(SIT(tick=341, threads=[th]), CTX(341))
        info = plan.infos[0]
        self.assertTrue(info.gift_bid)
        out = dom._apply_llm(plan, CTX(341), {"threads": [{"thread": 10, "move": "close", "price": None, "text": "",
                                                          "reason": "not worth it"}], "open": [], "lesson_ids": []})
        self.assertEqual([(a.kind, a.params["thread"]) for a in out if a.params.get("thread") == 10],
                         [("thread_message", 10)])
        self.assertLessEqual(out[0].params["price"], info.limit)

    def test_a_thread_the_code_would_close_at_once_still_gets_our_price(self):
        # live, tick 1176: Abuela opened SAL-08 at 29, our max was 19 and she stops near 23; the thread was
        # closed with no bid and the gift never came. With the window open the bid goes out first.
        off = {"id": 901, "maker": "abuela", "to": "t10", "give": {"types": ["card:LAT-02"]}, "want": {"cash": 14},
               "final": False, "status": "open", "created_tick": 341}
        th = {"id": 10, "kind": "persona", "with": "abuela", "topic": {"buy": {"card": "LAT-02"}}, "status": "open",
              "created_tick": 340, "messages": [{"tick": 341, "sender": "abuela", "text": "hola", "offer": off}],
              "standing_offers": [off]}
        closed = domain(last_gift=300)                                  # window closed: the code walks away
        out = [a for a in closed.fallback(SIT(tick=341, threads=[th]), CTX(341)) if a.params.get("thread") == 10]
        self.assertEqual([a.kind for a in out], ["close_thread"])
        dom = domain()
        plan = dom._prepare(SIT(tick=341, threads=[th]), CTX(341))
        info = plan.infos[0]
        self.assertTrue(info.gift_bid and not info.force_close)
        out = [a for a in dom.fallback(SIT(tick=341, threads=[th]), CTX(341)) if a.params.get("thread") == 10]
        self.assertEqual([a.kind for a in out], ["thread_message"])
        self.assertTrue(0 < out[0].params["price"] <= info.limit)

    def test_the_bid_goes_out_even_when_the_spend_budget_is_zero(self):
        # live, tick 1422, thread 2189: buy MAL-06 (we hold one: a second copy is worth ~8), Abuela at 29, all
        # spendable cash reserved for goals -> limit 0 -> closed with no bid and no gift.
        off = {"id": 901, "maker": "abuela", "to": "t10", "give": {"types": ["card:LAT-02"]}, "want": {"cash": 29},
               "final": False, "status": "open", "created_tick": 1422}
        th = {"id": 2189, "kind": "persona", "with": "abuela", "topic": {"buy": {"card": "LAT-02"}}, "status": "open",
              "created_tick": 1421, "messages": [{"tick": 1422, "sender": "abuela", "text": "hola", "offer": off}],
              "standing_offers": [off]}
        dom = domain(last_gift=1181)
        dom._spend_cap = lambda *a, **k: 0                              # goals and reserve leave nothing to spend
        out = [a for a in dom.fallback(SIT(tick=1422, cash=340, threads=[th]), CTX(1422))
               if a.params.get("thread") == 2189]
        self.assertEqual([a.kind for a in out], ["thread_message"])
        self.assertGreater(out[0].params["price"], 0)
        value = dom._prepare(SIT(tick=1422, cash=340, threads=[th]), CTX(1422)).infos[0]
        self.assertLess(out[0].params["price"], 29)                     # never her price: nothing can close above value
        closed = domain(last_gift=1300)                                 # window closed: no probe, the thread closes
        closed._spend_cap = lambda *a, **k: 0
        out = [a for a in closed.fallback(SIT(tick=1422, cash=340, threads=[th]), CTX(1422))
               if a.params.get("thread") == 2189]
        self.assertNotIn("thread_message", [a.kind for a in out])

    def test_no_flag_once_we_named_a_price_or_the_window_is_closed(self):
        dom = domain()
        th = S.thread([("d", 340, 27, S.CARD), ("u", 341, 12), ("d", 342, 26, S.CARD)])
        self.assertFalse(dom._prepare(SIT(tick=343, threads=[th]), CTX(343)).infos[0].gift_bid)
        th = S.thread([("d", 200, 27, S.CARD)])
        self.assertFalse(domain()._prepare(SIT(tick=201, threads=[th]), CTX(201)).infos[0].gift_bid)


class EggGift(unittest.TestCase):
    def test_an_easter_egg_card_from_the_dealer_restarts_the_clock_too(self):
        dom = domain(last_gift=1181)
        ev = {"id": 5, "tick": 1364, "type": "egg.given", "actor": "abuela",
              "payload": {"team": "t10", "cards": ["MAL-06"], "cash": 0, "packs": [], "reason": "easter egg"}}
        self.assertEqual(len(gifts.note_feed(dom.store.data, [ev], "t10")), 1)
        self.assertFalse(gifts.window_open(dom.store.data, "abuela", 1421))
        self.assertEqual(gifts.next_tick(dom.store.data, "abuela"), 1604)


class Memory(unittest.TestCase):
    def test_bootstrap_reads_our_gifts_from_the_recorded_feed(self):
        dom = domain(last_gift=None)
        rows = [{"id": 1, "tick": 657, "type": "gift.given", "actor": "abuela", "payload": {"team": "t10", "cards": ["LAV-05"]}},
                {"id": 2, "tick": 759, "type": "gift.given", "actor": "abuela", "payload": {"team": "t07", "cards": ["LAV-01"]}},
                {"id": 3, "tick": 929, "type": "gift.given", "actor": "abuela", "payload": {"team": "t10", "cards": ["MAL-02"]}}]
        (dom.store.path.parent / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
        s = SIT(tick=1100, cash=60, assets=[dict(a) for a in SPARES])
        s.me["id"] = "t10"
        self.assertEqual([a for a in dom.fallback(s, CTX(1100)) if a.kind == "open_thread"
                          and a.params.get("with") == "abuela"], [])
        self.assertEqual(gifts.next_tick(dom.store.data, "abuela"), 1169)
        s.tick = 1169
        self.assertEqual(len([a for a in dom.fallback(s, CTX(1169)) if a.kind == "open_thread"
                              and a.params.get("with") == "abuela"]), 1)

    def test_summary_for_the_brain(self):
        mem: dict = {}
        gifts.record(mem, "abuela", 657, ["LAV-05"])
        gifts.record(mem, "abuela", 929, ["MAL-02"])
        self.assertFalse(gifts.record(mem, "abuela", 929, ["MAL-02"]))
        row = gifts.summary(mem, 1100)["abuela"]
        self.assertEqual((row["last_gift_tick"], row["next_possible_tick"], row["gifts_received"], row["window_open"]),
                         (929, 1169, 2, False))


if __name__ == "__main__":
    unittest.main()


class CashCappedThread(unittest.TestCase):
    """A buy thread at a dealer without a step ladder (Abuela) whose next bid cash cannot cover waits a few ticks
    for cash and is then closed: it used to wait for ever and block her only slot."""

    def thread(self, dealer_tick):
        off = {"id": 901, "maker": "abuela", "to": "t10", "give": {"types": ["card:LAV-07"]}, "want": {"cash": 27},
               "final": False, "status": "expired", "created_tick": dealer_tick}
        return {"id": 77, "kind": "persona", "with": "abuela", "topic": {"buy": {"card": "LAV-07"}},
                "status": "open", "created_tick": dealer_tick - 9, "standing_offers": [],
                "messages": [{"tick": dealer_tick - 9, "sender": "abuela", "text": "28", "price": 28},
                             {"tick": dealer_tick - 1, "sender": "t10", "text": "17", "price": 17},
                             {"tick": dealer_tick, "sender": "abuela", "text": "27", "price": 27, "offer": off}]}

    def moves(self, now, dealer_tick=1500):
        dom = domain(last_gift=1490)                                   # the gift window is closed
        dom._spend_cap = lambda *a, **k: 13                            # the hour's spend leaves 13 P
        sit = SIT(tick=now, cash=340, threads=[self.thread(dealer_tick)])
        info = dom._prepare(sit, CTX(now)).infos[0]
        return info.move.kind, [a.kind for a in dom.fallback(sit, CTX(now)) if a.params.get("thread") == 77]

    def test_it_waits_a_few_ticks_for_cash(self):
        from bazaar.dealers.domain import CASH_HOLD_TICKS
        kind, acts = self.moves(1500 + CASH_HOLD_TICKS - 1)
        self.assertEqual((kind, acts), ("wait", []))

    def test_then_it_frees_the_dealers_slot(self):
        from bazaar.dealers.domain import CASH_HOLD_TICKS
        kind, acts = self.moves(1500 + CASH_HOLD_TICKS)
        self.assertEqual((kind, acts), ("close", ["close_thread"]))


class OneBuyThreadPerCard(unittest.TestCase):
    def plan(self, threads=()):
        import dataclasses
        dom = domain(last_gift=1490)
        p = dom._prepare(SIT(tick=1500, cash=300, assets=[], threads=list(threads)), CTX(1500))
        first = next(c for c in p.candidates if c.kind.startswith("buy"))
        p.candidates.append(dataclasses.replace(first, id="c99", dealer="chato"))
        p.free = sorted(set(p.free) | {"abuela", "chato"})
        return dom, p, first

    def test_the_same_card_is_not_opened_at_two_dealers_in_one_tick(self):
        dom, p, first = self.plan()
        acts = dom._open_actions(p, [(first.id, ""), ("c99", "")], "fallback")
        self.assertEqual([(a.params["with"], a.params["topic"]["buy"]["card"]) for a in acts],
                         [(first.dealer, first.item)])
