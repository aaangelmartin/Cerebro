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
        self.assertEqual(acts[0].params["venue"], "v10")                      # the ally, never v07
        d.observe(Outcome(acts[0].id, 100, "sent", {"id": 5}))
        self.assertIn("our own venue", S.post_history()[-1]["detail"])
        with mock.patch.object(S, "post_offers", return_value=[{**POST, "venue": "v07", "want_cash": 25}]):
            acts = domain()._brain_posts(me, [], lambda a, c: True, {"SAL-07": 1}, {"avoid_post_venues": ["v10"]}, 100)
        self.assertEqual(acts[0].params["venue"], "rastro")                   # ally avoided: El Rastro

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
