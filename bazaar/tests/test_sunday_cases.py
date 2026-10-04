"""Sunday's special cases, each on the real code: the clock jumping three hours at the open, the 150 P allowance,
Don Ernesto and his prices under our deal cap, and the packs nobody on the team wants bought."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bazaar import config
from bazaar.core import rails
from bazaar.core.types import Action
from bazaar.dealers.domain import DealersDomain
from bazaar.dealers.tests import test_domain as T
from bazaar.dealers.values import Values, pack_value
from bazaar.tests import test_run as TR

# Sunday's real menus (recorded Saturday 23:00): what each dealer asks for a pack, and Don Ernesto's desk
PACKS = {"abuela": ("sobre_barrio", 26, 30), "chato": ("sobre_plata", 150, 188), "banco": ("sobre_oro", 420, 546)}
ERNESTO = {"id": "banco", "name": "Don Ernesto", "status": "active", "level": 5, "kind": "banker", "enabled": True,
           "open_to_all": True, "traits": {"patience": 0.95, "generosity": 0.1, "shrewdness": 0.95, "strictness": 1.0},
           "menu": {"sells": [{"pack": "sobre_oro", "name": "Gold pack", "list_price": 420, "opening_ask": 546,
                               "per_team_per_hour": 1},
                              {"rarity": "legendary", "sets": "released", "list_price": 585}],
                    "buys": [{"rarity": "epic", "sets": "released"}, {"rarity": "legendary", "sets": "released"}],
                    "deals_per_team_per_hour": 4}}
AFFINITY = {"LAV": 1.6, "MAL": 1.3, "LAT": 0.5, "SAL": 0.9, "RET": 1.1, "CHA": 0.7}
CONTROL = {"armed": True, "max_spend_per_deal": 210, "max_spend_per_hour": 550, "cash_reserve": 5}


class ClockJump(unittest.TestCase):
    """At 09:00 the game clock is expected to jump from h13.37 to h16.65 with the tick going on by one."""

    def setUp(self):
        self.base = TR.RunTest("test_disarmed_is_dry_run")
        self.base.setUp()
        self.addCleanup(self.base.tearDown)

    def test_the_jump_and_the_allowance_do_not_trip_a_breaker(self):
        r = self.base.runner([TR.Dom("market")])
        r.step(TR.sit_at(tick=1445, seconds=30.0, cash=340, collection=1819.0, t_hours=13.3667))
        r.step(TR.sit_at(tick=1446, seconds=15.0, cash=340, collection=1819.0, t_hours=16.65))   # three hours later
        r.step(TR.sit_at(tick=1458, seconds=15.0, cash=490, collection=1819.0, t_hours=16.70))   # +150 P for all
        self.assertLess(r.cautious_until, 1458)
        self.assertFalse([e for e in r.errors if "breaker" in json.dumps(e, default=str)])
        self.assertEqual(r.last_tick, 1458)

    def test_the_hour_of_spend_is_real_time_and_survives_the_jump(self):
        r = self.base.runner([TR.Dom("market")])
        r.budget.state["spend"].append([r.now(), 200])
        r.step(TR.sit_at(tick=1445, seconds=30.0, cash=340, t_hours=13.3667))
        r.step(TR.sit_at(tick=1446, seconds=15.0, cash=340, t_hours=16.65))
        self.assertEqual(sum(p for _, p in r.budget.state["spend"]), 200)           # not forgotten with the game hour
        self.assertEqual(r.budget.for_tick(1446, hour_cap=550)["spend_hour_left"], 350)


class DonErnesto(unittest.TestCase):
    """Nothing with Don Ernesto without Ángel's OK. In code that is the deal cap: everything he sells costs more
    than 210 P, and the epics he would buy are protected by name."""

    def sit(self, cash=490, assets=None):
        s = T.AuditFixes().sit(tick=1500, cash=cash, assets=assets or [], dealers=[ERNESTO])
        s.me["affinity"] = dict(AFFINITY)
        return s

    def ctx(self, control):
        c = T.AuditFixes().ctx(1500)
        c.control = control
        return c

    def test_the_code_opens_nothing_with_him_under_the_cap(self):
        dom = T.domain()
        dom._brain_orders = lambda: []
        acts = dom.fallback(self.sit(), self.ctx(dict(CONTROL)))
        self.assertEqual([a for a in acts if a.params.get("with") == "banco"], [])

    def legendary_offer(self, price):
        offer = {"id": 7, "maker": "banco", "to": "t10", "thread": 3, "status": "open",
                 "give": {"cash": 0, "assets": [], "types": ["card:LAV-12"]}, "want": {"cash": price}}
        s = self.sit(cash=800)
        s.threads = [{"id": 3, "kind": "persona", "with": "banco", "topic": {"buy": {"card": "LAV-12"}},
                      "status": "open", "standing_offers": [offer], "messages": []}]
        s.values = {"LAV-12": 720.0}
        return s, Action("accept_offer", {"offer": 7, "expect": offer}, "dealers",
                         expected={"value_get": 720.0, "spend": price})

    def test_the_rails_veto_his_legendary_under_our_deal_cap(self):
        # Even a brain order or a model that wanted it: 585 P (his list price) and 470 P (the price the brief
        # hints at) are both over the 210 P a deal may cost, whatever the card is worth to us.
        for price in (585, 470, 240):
            s, a = self.legendary_offer(price)
            v = rails.check(a, s, self.ctx(dict(CONTROL)))
            self.assertFalse(v.ok, (price, v))
            self.assertEqual(v.rail, "cash", (price, v))

    def test_raising_the_cap_is_the_ok(self):
        s, a = self.legendary_offer(470)
        c = self.ctx({**CONTROL, "max_spend_per_deal": 500, "max_spend_per_hour": 1000})
        c.budget["spend_hour_cap"] = 1000
        v = rails.check(a, s, c)
        self.assertTrue(v.ok or v.rail != "cash", v)        # the deal cap no longer stops it; value 720 > 470

    def test_our_epics_are_protected_so_he_cannot_buy_them(self):
        epic = {"id": 9, "kind": "card", "ref": "MAL-11", "rarity": "epic", "set": "MAL", "your_value": 234.0}
        dom = T.domain()
        dom._brain_orders = lambda: []
        acts = dom.fallback(self.sit(assets=[epic]), self.ctx({**CONTROL, "protected": ["MAL-11"]}))
        self.assertEqual([a for a in acts if a.kind == "open_thread"], [])


class NoPacks(unittest.TestCase):
    """No pack is bought: to us each one is worth less than half its price, far from the 1.25 x edge the code asks
    for, with Chamberí released or not."""

    HELD = ([f"LAV-{i:02d}" for i in range(1, 11)] + [f"MAL-{i:02d}" for i in range(1, 12)]
            + [f"RET-{i:02d}" for i in range(1, 12)] + [f"SAL-{i:02d}" for i in range(1, 6)] + ["LAT-02", "LAT-04"])

    def values(self, cha: bool) -> Values:
        """Our hand on Sunday morning: three full pages, MAL-11, RET-11, half of Salamanca, two La Latina."""
        cat = json.loads((config.ROOT / "sim" / "data" / "catalog.json").read_text())
        for s in cat["sets"]:
            s["released"] = s["id"] != "CHA" or cha
        assets = [{"id": i, "kind": "card", "ref": r, "set": r[:3]} for i, r in enumerate(self.HELD, 1)]
        return Values({"affinity": dict(AFFINITY), "assets": assets}, cat)

    def test_every_pack_is_worth_less_than_it_costs(self):
        for cha in (False, True):
            v = self.values(cha)
            for dealer, (pack, list_price, opening) in PACKS.items():
                worth = pack_value(pack, v)
                self.assertLess(worth, list_price, (dealer, pack, cha))
                self.assertFalse(DealersDomain._pack_ok(worth, opening), (dealer, pack, cha))
                self.assertFalse(DealersDomain._pack_ok(worth, list_price), (dealer, pack, cha))
                self.assertLess(DealersDomain._pack_max(worth), 0.6 * list_price, (dealer, pack, cha))

    def test_the_rails_refuse_a_pack_thread_at_its_price(self):
        live = Path(tempfile.mkdtemp(prefix="sunday-"))
        (live / "control.json").write_text(json.dumps(CONTROL))
        a = Action("open_thread", {"with": "chato", "topic": {"buy": {"pack": "sobre_plata"}}, "max_price": 188},
                   "dealers", expected={"value_get": 300.0, "spend": 188})      # the proposer's own hint is ignored
        s = T.AuditFixes().sit(tick=1500, cash=490)
        s.me["affinity"] = dict(AFFINITY)
        c = T.AuditFixes().ctx(1500)
        c.control = dict(CONTROL)
        self.assertIsNotNone(rails.check(a, s, c))                            # opening a thread costs nothing;
        # the price is what the rail guards: accepting his 188 P offer for a pack worth ~85 to us is vetoed
        offer = {"id": 7, "maker": "chato", "to": "t10", "thread": 3, "status": "open",
                 "give": {"cash": 0, "assets": [], "types": ["pack:sobre_plata"]}, "want": {"cash": 188}}
        s.threads = [{"id": 3, "kind": "persona", "with": "chato", "topic": {"buy": {"pack": "sobre_plata"}},
                      "status": "open", "standing_offers": [offer], "messages": []}]
        acc = Action("accept_offer", {"offer": 7, "expect": offer}, "dealers",
                     expected={"value_get": 300.0, "spend": 188})
        verdict = rails.check(acc, s, c)
        self.assertFalse(verdict.ok, verdict)


if __name__ == "__main__":
    unittest.main()
