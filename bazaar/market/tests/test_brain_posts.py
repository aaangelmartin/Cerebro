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


if __name__ == "__main__":
    unittest.main()
