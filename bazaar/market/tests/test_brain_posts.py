import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bazaar import config
from bazaar.brain import strategy as S
from bazaar.core.types import Outcome
from bazaar.market.domain import MarketDomain
from bazaar.market.rivals import RivalModel


def domain():
    return MarketDomain(rivals=RivalModel(Path(tempfile.mkdtemp()) / "r.json", seed=False), catalog={}, use_llm=False)


ME = {"assets": [{"id": 1, "kind": "card", "ref": "SAL-07", "your_value": 22.5}]}
POST = {"give": "SAL-07", "want_card": None, "want_cash": 24, "to": None, "venue": "rastro", "why": "test"}


class BrainPostsTest(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(config, "LIVE", self.live)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def run_once(self, d, posts, tick=100):
        with mock.patch.object(S, "post_offers", return_value=posts):
            return d._brain_posts(ME, [], lambda a, c: True, {"SAL-07": 1}, {}, tick)

    def test_vetoed_identical_post_is_never_resent_but_a_corrected_one_is(self):
        d = domain()
        acts = self.run_once(d, [POST])
        self.assertEqual(len(acts), 1)
        d.observe(Outcome(acts[0].id, 100, "vetoed", {"rail": "never_lose", "detail": "ask 24 < floor 25"}))
        rows = S.post_history()
        self.assertEqual((rows[-1]["status"], rows[-1]["rail"]), ("vetoed", "never_lose"))
        self.assertIn("vetoed by never_lose: ask 24 < floor 25", S.post_outcomes_text())
        self.assertEqual(self.run_once(domain(), [POST], 101), [])             # identical: blocked (also after restart)
        fixed = self.run_once(domain(), [{**POST, "want_cash": 26}], 101)       # corrected price: allowed
        self.assertEqual(len(fixed), 1)

    def test_successful_post_is_not_repeated_soon(self):
        d = domain()
        acts = self.run_once(d, [POST])
        d.observe(Outcome(acts[0].id, 100, "sent", {"id": 999}))
        self.assertEqual(S.post_history()[-1]["offer_id"], 999)
        self.assertEqual(self.run_once(domain(), [POST], 150), [])
        self.assertEqual(len(self.run_once(domain(), [POST], 100 + 121)), 1)

    def test_post_on_our_own_venue_is_rerouted_and_the_brain_is_told(self):
        d = domain()
        me = {**ME, "venue": "v07"}
        with mock.patch.object(S, "post_offers", return_value=[{**POST, "venue": "v07"}]):
            acts = d._brain_posts(me, [], lambda a, c: True, {"SAL-07": 1}, {}, 100)
        self.assertEqual(acts[0].params["venue"], "rastro")                   # no allies: El Rastro, never v07
        d.observe(Outcome(acts[0].id, 100, "sent", {"id": 5}))
        self.assertIn("our own venue", S.post_history()[-1]["detail"])
        from bazaar.market import protocol as proto
        with mock.patch.object(proto, "allied_venues", return_value={"v10": "t05"}):
            with mock.patch.object(S, "post_offers", return_value=[{**POST, "venue": "v07", "want_cash": 25}]):
                acts = domain()._brain_posts(me, [], lambda a, c: True, {"SAL-07": 1}, {}, 100)
            self.assertEqual(acts[0].params["venue"], "v10")                  # an ally named in control: there
            with mock.patch.object(S, "post_offers", return_value=[{**POST, "venue": "v07", "want_cash": 26}]):
                acts = domain()._brain_posts(me, [], lambda a, c: True, {"SAL-07": 1},
                                             {"avoid_post_venues": ["v10"]}, 100)
            self.assertEqual(acts[0].params["venue"], "rastro")               # ally avoided: El Rastro

    def test_plan_accept_outcomes_reach_the_brain(self):
        d = domain()
        d._note_brain_accepts({5143: "gain 0.5 P after fees is below the minimum 1.0 P"}, 351)
        d._note_brain_accepts({5143: "gain 0.5 P after fees is below the minimum 1.0 P"}, 352)   # same reason: once
        rows = [r for r in S.post_history() if r.get("kind") == "accept"]
        self.assertEqual(len(rows), 1)
        d._record_brain_accept(5143, Outcome("a1", 353, "vetoed", {"rail": "value", "detail": "gain -1"}))
        text = S.post_outcomes_text()
        self.assertIn("accept #5143 -> skipped: gain 0.5 P", text)
        self.assertIn("accept #5143 -> vetoed by value: gain -1", text)
        self.assertEqual(self.run_once(domain(), [POST], 354).__len__(), 1)   # accept rows never block a post

    def test_plain_plan_accept_only_needs_to_create_value(self):
        """Offer 5143: t12 paid 8 P for a LAV-04 worth 4 to us (2 copies held). No last-copy exception is
        needed, so the 5 P keep-one minimum must not apply."""
        d = domain()
        me = {"id": "t10", "cash": 30, "assets": [
            {"id": 11, "kind": "card", "ref": "LAV-04", "set": "LAV", "rarity": "common", "your_value": 4.0},
            {"id": 12, "kind": "card", "ref": "LAV-04", "set": "LAV", "rarity": "common", "your_value": 16.0}]}
        offer = {"id": 5143, "maker": "t12", "to": "t10", "venue": "rastro", "status": "open", "thread": None,
                 "give": {"cash": 8, "assets": [], "types": []},
                 "want": {"cash": 0, "assets": [], "types": ["card:LAV-04"]}, "expires_tick": 400}
        sit = {"tick": 351, "me": me, "my_offers": [offer], "venues": [], "rastro_book": [], "feed_new": [],
               "limits": {}}
        with mock.patch.object(S, "accept_offers", return_value={5143}):
            acts = d.fallback(sit, {"control": {}, "budget": {}})
        acc = [a for a in acts if a.kind == "accept_offer"]
        self.assertEqual([a.params["offer"] for a in acc], [5143])
        self.assertEqual(acc[0].source, "council")


if __name__ == "__main__":
    unittest.main()


class BrainPostSkipsTest(unittest.TestCase):
    """A planned post that cannot go out says why, and a card tied up in an older offer of ours is freed."""

    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(config, "LIVE", self.live)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    ME10 = {"assets": [{"id": 797, "kind": "card", "ref": "SAL-10", "your_value": 63}]}
    ASK = {"give": "SAL-10", "want_card": None, "want_cash": 78, "to": "t08", "venue": "rastro", "why": "fund MAL-09"}
    OLD = {"id": 8084, "maker": "t10", "status": "open", "give": {"cash": 0, "assets": [{"id": 797, "ref": "SAL-10"}]},
           "want": {"cash": 0, "types": ["card:LAV-11"]}}

    def run_once(self, d, posts, own, can_give, tick=600):
        with mock.patch.object(S, "post_offers", return_value=posts):
            return d._brain_posts(self.ME10, own, can_give, {"SAL-10": 1}, {}, tick)

    def test_card_inside_an_older_offer_is_freed_and_reported(self):
        d = domain()
        acts = self.run_once(d, [self.ASK], [self.OLD], lambda a, c: False)     # reserved by offer 8084
        self.assertEqual([(a.kind, a.params) for a in acts], [("cancel_offer", {"offer": 8084})])
        row = S.post_history()[-1]
        self.assertEqual(row["status"], "skipped")
        self.assertIn("#8084", row["detail"])
        acts = self.run_once(d, [self.ASK], [], lambda a, c: True, tick=601)    # next tick: free, goes out
        self.assertEqual([a.kind for a in acts], ["post_offer"])
        self.assertEqual(acts[0].params["want"], {"cash": 78})

    def test_protected_offer_is_never_cancelled_for_a_new_post(self):
        d = domain()
        hand = {**self.OLD, "id": 12189, "to": "t08", "want": {"cash": 160, "types": []}, "created_tick": 798}
        with mock.patch.object(S, "post_offers", return_value=[self.ASK]):
            acts = d._brain_posts(self.ME10, [hand], lambda a, c: False, {"SAL-10": 1},
                                  {"protected_offers": [12189]}, 800)
        self.assertEqual(acts, [])                                           # no cancel, no post
        self.assertIn("protected/human offer #12189", S.post_history()[-1]["detail"])

    def test_hand_posted_offer_is_never_cancelled_for_a_new_post(self):
        d = domain()
        with mock.patch.object(S, "post_offers", return_value=[]):           # first tick: the bot adopts what is open
            d._brain_posts(self.ME10, [], lambda a, c: True, {"SAL-10": 1}, {}, 790)
        d._bot_rec([], {}, 790)
        hand = {**self.OLD, "id": 12088, "to": "t08", "want": {"cash": 160, "types": []}, "created_tick": 793}
        acts = self.run_once(d, [self.ASK], [hand], lambda a, c: False, tick=795)
        self.assertEqual(acts, [])
        self.assertIn("#12088", S.post_history()[-1]["detail"])
        self.assertEqual(d._hands_off(hand, [hand], {}, 795), "human")
        mine = {**self.OLD, "id": 500, "created_tick": 794}                  # an offer the bot posted itself
        d._bot_offers["ids"].add("500")
        self.assertEqual(d._hands_off(mine, [mine], {}, 795), "")

    def test_two_planned_offers_for_one_card_report_the_conflict(self):
        d = domain()
        swap = {"give": "SAL-10", "want_card": "LAV-11", "want_cash": None, "to": "t08", "venue": "rastro"}
        acts = self.run_once(d, [swap, self.ASK], [self.OLD], lambda a, c: False)
        self.assertEqual(acts, [])                                           # nothing cancelled: both are planned
        self.assertIn("two offers", S.post_history()[-1]["detail"])

    def test_no_copy_and_refused_posts_are_logged_once(self):
        d = domain()
        with mock.patch.object(S, "post_offers", return_value=[self.ASK]):
            for t in (600, 601, 602):
                d._brain_posts({"assets": []}, [], lambda a, c: True, {}, {}, t)
        rows = [r for r in S.post_history() if r.get("status") == "skipped"]
        self.assertEqual(len(rows), 1)
        self.assertIn("no copy", rows[0]["detail"])
        self.assertIn("skipped: we hold no copy", S.post_outcomes_text())


class BrainAcceptReasonTest(unittest.TestCase):
    """A vetoed accept tells the brain which rule blocked it and with what number."""

    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(config, "LIVE", self.live)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_council_and_arbiter_vetoes_carry_their_reason(self):
        d = domain()
        d._record_brain_accept(8169, Outcome("a1", 560, "vetoed", {"by": "council", "why": "auditor: pays 83 vs ask 78"}))
        d._record_brain_accept(8169, Outcome("a2", 582, "vetoed", {
            "rail": "arbiter", "detail": "accept already used this tick (cap 1 offer accept per tick; retried next tick)"}))
        d._record_brain_accept(8169, Outcome("a3", 583, "vetoed", {
            "rail": "cash", "detail": "spend 83 > per-deal cap 50"}))
        rows = S.post_history()
        self.assertEqual([(r["rail"], r["detail"][:20]) for r in rows],
                         [("council", "auditor: pays 83 vs "), ("arbiter", "accept already used "),
                          ("cash", "spend 83 > per-deal ")])
        text = S.post_outcomes_text()
        self.assertIn("accept #8169 -> vetoed by council: auditor: pays 83 vs ask 78", text)
        self.assertIn("vetoed by cash: spend 83 > per-deal cap 50", text)


class OrderedCardsTest(unittest.TestCase):
    """Cards the brain ordered sold to a dealer are not listed by the market (outbox request code-578abca3)."""

    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(config, "LIVE", self.live)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    ORDER = {"dealer": "picaros", "action": "sell", "ref": "LAV-04", "open": 8, "bound": 5, "max_messages": 3}

    def test_active_sell_order_holds_the_card_until_it_ends(self):
        with mock.patch.object(S, "dealer_orders", return_value=[self.ORDER, {**self.ORDER, "action": "buy",
                                                                               "ref": "SAL-05"}]):
            self.assertEqual(S.ordered_sell_refs(), {"LAV-04"})          # buys hold nothing
            S.record_post({"kind": "dealer_order", "dealer": "picaros", "action": "sell", "ref": "LAV-04",
                           "bound": 5, "status": "waiting"})
            self.assertEqual(S.ordered_sell_refs(), {"LAV-04"})
            S.record_post({"kind": "dealer_order", "dealer": "picaros", "action": "sell", "ref": "LAV-04",
                           "bound": 5, "status": "no_deal"})
            self.assertEqual(S.ordered_sell_refs(), set())               # ended: the market may list it again
        with mock.patch.object(S, "dealer_orders", return_value=[{**self.ORDER, "bound": 6}]):
            self.assertEqual(S.ordered_sell_refs(), {"LAV-04"})          # a new bound is a new order

    def test_the_market_does_not_post_an_ordered_card(self):
        from types import SimpleNamespace
        me = {"id": "t10", "cash": 30, "affinity": {"LAV": 1.6}, "assets": [
            {"id": 1, "kind": "card", "ref": "LAV-04", "rarity": "common", "set": "LAV", "your_value": 16},
            {"id": 2, "kind": "card", "ref": "LAV-04", "rarity": "common", "set": "LAV", "your_value": 4}]}
        sit = SimpleNamespace(tick=10, me=me, my_offers=[], threads=[], venues=[], feed_new=[], limits={}, books={})
        ctx = SimpleNamespace(control={}, budget={}, cautious=False, llm_ok=False)

        def given(orders):
            with mock.patch.object(S, "dealer_orders", return_value=orders), \
                    mock.patch.object(S, "post_offers", return_value=[]):
                _, posts, state = domain()._prepare(sit, ctx)
            return {p.asset.get("ref") for p in posts} | {s.asset.get("ref") for s in state.get("_swaps") or []}

        self.assertIn("LAV-04", given([]))
        self.assertNotIn("LAV-04", given([self.ORDER]))

    def test_the_market_does_not_post_a_card_the_plan_reserves(self):
        """reserved_refs keeps a card out of every team offer (outbox request code-fc46e966)."""
        from types import SimpleNamespace
        self.assertEqual(S.sanitize({"reserved_refs": ["sal-10", "nope", "SAL-08"]})["reserved_refs"],
                         ["SAL-08", "SAL-10"])
        self.assertNotIn("reserved_refs", S.sanitize({}))                # omitted = keep the previous list
        me = {"id": "t10", "cash": 30, "affinity": {"LAV": 1.6}, "assets": [
            {"id": 1, "kind": "card", "ref": "LAV-04", "rarity": "common", "set": "LAV", "your_value": 16},
            {"id": 2, "kind": "card", "ref": "LAV-04", "rarity": "common", "set": "LAV", "your_value": 4}]}
        sit = SimpleNamespace(tick=10, me=me, my_offers=[], threads=[], venues=[], feed_new=[], limits={}, books={})
        ctx = SimpleNamespace(control={}, budget={}, cautious=False, llm_ok=False)

        def given(held):
            with mock.patch.object(S, "dealer_orders", return_value=[]), \
                    mock.patch.object(S, "post_offers", return_value=[]), \
                    mock.patch.object(S, "reserved_refs", return_value=set(held)):
                _, posts, state = domain()._prepare(sit, ctx)
            return {p.asset.get("ref") for p in posts} | {s.asset.get("ref") for s in state.get("_swaps") or []}

        self.assertIn("LAV-04", given([]))
        self.assertNotIn("LAV-04", given(["LAV-04"]))


class BrainReservedSpareTest(unittest.TestCase):
    """The fallback does not relist a spare the brain's plan gives in a post (outbox request code-4136c8c6)."""

    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(config, "LIVE", self.live)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    SWAP = {"give": "LAV-05", "want_card": "LAT-08", "want_cash": None, "to": "t17", "venue": "rastro",
            "why": "swap the spare for a card we lack"}
    ME = {"id": "t10", "cash": 30, "affinity": {"LAV": 1.6}, "assets": [
        {"id": 367, "kind": "card", "ref": "LAV-05", "rarity": "common", "set": "LAV", "your_value": 16},
        {"id": 368, "kind": "card", "ref": "LAV-05", "rarity": "common", "set": "LAV", "your_value": 4}]}

    def tick(self, d, plan, my_offers=(), tick=894):
        from types import SimpleNamespace
        sit = SimpleNamespace(tick=tick, me=self.ME, my_offers=list(my_offers), threads=[], venues=[], feed_new=[],
                              limits={}, books={})
        ctx = SimpleNamespace(control={}, budget={}, cautious=False, llm_ok=False)
        with mock.patch.object(S, "post_offers", return_value=plan), \
                mock.patch.object(S, "dealer_orders", return_value=[]):
            return d.fallback(sit, ctx)

    @staticmethod
    def gives(acts):
        return [(a.source, (a.params.get("give") or {}).get("assets"), a.params.get("want"))
                for a in acts if a.kind == "post_offer"]

    def test_fallback_lists_the_spare_when_the_brain_does_not_plan_it(self):
        self.assertIn([368], [g for _, g, _ in self.gives(self.tick(domain(), []))])

    def test_brain_swap_goes_out_first_and_the_fallback_leaves_the_spare(self):
        acts = self.tick(domain(), [self.SWAP])
        posts = self.gives(acts)
        self.assertEqual(posts[0], ("council", [368], {"cards": ["LAT-08"]}))
        self.assertEqual([p for p in posts if p[0] != "council" and set(p[1] or []) & {367, 368}], [])
        self.assertEqual(acts[0].kind, "post_offer")                     # ahead of every fallback action

    def test_spare_tied_in_a_fallback_offer_is_freed_then_swapped_without_a_relist(self):
        d = domain()
        old = {"id": 13793, "maker": "t10", "status": "open", "thread": None, "venue": "rastro",
               "give": {"cash": 0, "assets": [{"id": 368, "ref": "LAV-05"}]}, "want": {"cash": 6}}
        with mock.patch.object(d, "_hands_off", return_value=None):      # a bot-posted, unprotected offer
            acts = self.tick(d, [self.SWAP], [old])
        self.assertIn(("cancel_offer", {"offer": 13793}), [(a.kind, a.params) for a in acts])
        self.assertEqual([p for p in self.gives(acts) if set(p[1] or []) & {367, 368}], [])
        self.assertIn("cancelling it now", S.post_history()[-1]["detail"])
        posts = self.gives(self.tick(d, [self.SWAP], tick=895))           # freed: the swap, not a new 6 P ask
        self.assertEqual([p for p in posts if set(p[1] or []) & {367, 368}],
                         [("council", [368], {"cards": ["LAT-08"]})])

    def test_a_refused_brain_post_does_not_hold_the_spare(self):
        S.record_post({**self.SWAP, "tick": 890, "status": "refused"})
        self.assertIn([368], [g for _, g, _ in self.gives(self.tick(domain(), [self.SWAP]))])
