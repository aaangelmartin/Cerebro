"""The card that completes a page: its value carries the page bonus everywhere a price is capped, and a cheap
one (common/uncommon) is bought from a team, never from a dealer."""
import unittest
from unittest import mock

from bazaar.core import rails
from bazaar.core.goal import completes_page, last_card_value, pending, strategy_goals, team_only
from bazaar.core.types import Action
from bazaar.dealers.values import Values
from bazaar.strategist import brainio

from .test_rails import accept, card, ctx, offer, sit

RARITY = ["common"] * 5 + ["uncommon"] * 3 + ["rare"] * 2
BOOK = {"common": 10, "uncommon": 25, "rare": 70}
CATALOG = {"values": {"page_bonus": 0.25, "copy_marginals": [1.0, 0.25, 0.1]},
           "sets": [{"id": "SAL", "released": True,
                     "cards": [{"id": f"SAL-{i:02d}", "rarity": r, "book": BOOK[r], "page": True}
                               for i, r in enumerate(RARITY, 1)]}]}
BONUS = 0.25 * 0.9 * 265                       # 59.6: page bonus share x our SAL multiplier x the page's book


def me(missing):
    assets = [card(i, f"SAL-{i:02d}", 9.0) for i in range(1, 11) if f"SAL-{i:02d}" not in missing]
    return {"id": "t10", "cash": 300, "venue": "v99", "affinity": {"SAL": 0.9}, "assets": assets}


def values(missing, exact=None):
    return Values(me(missing), CATALOG, exact or {})


class LastCardValue(unittest.TestCase):
    def test_the_estimate_gains_the_page_bonus_only_for_the_last_card(self):
        self.assertAlmostEqual(last_card_value(values({"SAL-05"}), "SAL-05"), 9.0 + BONUS, places=1)
        far = values({"SAL-05", "SAL-06", "SAL-07", "SAL-09", "SAL-10"})   # Saturday night: 5 cards missing
        self.assertFalse(completes_page(far, "SAL-05"))
        self.assertAlmostEqual(last_card_value(far, "SAL-05"), 9.0)

    def test_the_game_figure_already_has_the_bonus_and_is_not_doubled(self):
        v = values({"SAL-05"})
        v.remember_exact("SAL-05", {"value": 68.6})
        self.assertAlmostEqual(last_card_value(v, "SAL-05"), 68.6, places=1)

    def test_goal_cap_counts_the_bonus(self):
        with mock.patch("bazaar.brain.strategy.goal_buys", return_value={"SAL-05": 30}):
            self.assertEqual(strategy_goals(values({"SAL-05"})), {"SAL-05": 30})
            self.assertEqual(strategy_goals(values({"SAL-05", "SAL-09"})), {"SAL-05": 8})   # not the last: no bonus


class TeamOnly(unittest.TestCase):
    def test_cheap_last_card_is_kept_for_a_team_seller(self):
        v = values({"SAL-05"})
        self.assertTrue(team_only(v, {}, "SAL-05"))
        self.assertFalse(team_only(values({"SAL-10"}), {}, "SAL-10"))          # a rare: any seller
        self.assertFalse(team_only(values({"SAL-05", "SAL-09"}), {}, "SAL-05"))
        self.assertFalse(team_only(v, {"goal_buys": {"SAL-05": 30}}, "SAL-05"))  # the operator's goal: any seller

    def test_dealers_do_not_see_it_and_the_market_does(self):
        v = values({"SAL-05"})
        s = {"me": me({"SAL-05"})}
        with mock.patch("bazaar.brain.strategy.goal_buys", return_value={"SAL-05": 30}):
            self.assertEqual(pending(s, {}, v), {})
            self.assertEqual(pending(s, {}, v, team=True), {"SAL-05": 30})
            self.assertEqual(pending(s, {"goal_buys": {"SAL-05": 25}}, v), {"SAL-05": 25})

    def test_a_rare_last_card_stays_a_goal_for_everyone(self):
        v = values({"SAL-10"})
        with mock.patch("bazaar.brain.strategy.goal_buys", return_value={"SAL-10": 60}):
            self.assertEqual(pending({"me": me({"SAL-10"})}, {}, v), {"SAL-10": 60})


class Rail(unittest.TestCase):
    """The value rail needs no change: at 9/10 the game's value of the missing card includes the bonus."""

    def check(self, action, threads=()):
        c = ctx(control={"armed": True, "max_spend_per_deal": 200}, value=lambda ref: {"SAL-05": 68.6}.get(ref))
        with mock.patch.object(rails, "_catalog", lambda: CATALOG):
            return rails.check(action, sit(me=me({"SAL-05"}), threads=list(threads), values={}), c)

    def test_a_team_offer_at_30_passes(self):
        self.assertTrue(self.check(accept(offer({"assets": [{"id": 50, "ref": "SAL-05"}]}, {"cash": 30}))).ok)

    def test_our_bid_at_30_passes(self):
        post = Action("post_offer", {"venue": "rastro", "give": {"cash": 30}, "want": {"cards": ["SAL-05"]}}, "market")
        self.assertTrue(self.check(post).ok)

    def test_an_open_dealer_thread_for_it_turns_the_team_offer_into_a_spare(self):
        # why the dealers must stay off the last card: with their thread open the team purchase is refused
        t = {"id": 5, "with": "abuela", "status": "open", "topic": {"buy": {"card": "SAL-05"}}, "messages": []}
        v = self.check(accept(offer({"assets": [{"id": 50, "ref": "SAL-05"}]}, {"cash": 30})), [t])
        self.assertEqual(v.rail, "value")


class PlanValidator(unittest.TestCase):
    def pic(self, m):
        return {"sets": {"SAL": {"missing": [m]}}, "held_refs": [], "control": {}}

    def errors(self, m):
        return [e for e in brainio.validate({"goal_buys": {"SAL-05": 30}}, self.pic(m)) if e.startswith("goal")]

    def test_goal_below_the_value_with_bonus_is_valid(self):
        self.assertEqual(self.errors({"ref": "SAL-05", "value_to_us": 9.0, "value_with_page_bonus": 68.6}), [])

    def test_goal_above_the_plain_value_is_still_refused_far_from_the_page(self):
        self.assertTrue(self.errors({"ref": "SAL-05", "value_to_us": 9.0}))


if __name__ == "__main__":
    unittest.main()
