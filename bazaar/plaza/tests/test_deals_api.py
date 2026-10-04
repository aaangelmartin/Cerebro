"""Deals: the blind price, the life of a match read from the game's feed, and the deals routes."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.plaza import deals as D
from bazaar.plaza import feed as F
from bazaar.plaza import matcher as M
from bazaar.plaza import private, quotes, safe
from bazaar.plaza.store import PlazaError
from bazaar.plaza.tests import test_server as T
from bazaar.plaza.tests.test_matcher import CAT, agent, sheets


def listed(tick, maker, to, ref, price, oid=1, venue=None):
    return {"t": "listed", "tick": tick, "id": oid, "maker": maker, "to": to, "side": "bid", "ref": ref,
            "ref_back": None, "price": price, **({"venue": venue} if venue else {})}


def settled(tick, a, b, ref, price, venue=None, sid=None):
    return {"t": "settled", "tick": tick, "parties": [a, b], "refs": [ref], "price": price,
            **({"venue": venue} if venue else {}), **({"id": sid} if sid else {})}


class QuoterTest(unittest.TestCase):
    """The price never lets a team work out the other side's limit."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.v = private.Vault(Path(self.dir.name) / "p")
        self.q = quotes.Quoter(self.v)

    def tearDown(self):
        self.dir.cleanup()

    def limits(self, lo, hi, v_sell=None, v_buy=None):
        """Straight into the vault: the cooldown on edits is the team API's business, not this test's."""
        with self.v.lock:
            self.v.data["t01"] = {"SAL-09": {"min": lo, **({"value": v_sell} if v_sell else {})}}
            self.v.data["t02"] = {"SAL-09": {"max": hi, **({"value": v_buy} if v_buy else {})}}

    def ask(self, ref_price=70, floor=40, **kw):
        return self.q.at(self.q.tick + quotes.HOLD_TICKS).quote("t01", "t02", "SAL-09", ref_price, floor, **kw)

    def test_overlap_gives_a_price_inside_it_and_no_overlap_gives_nothing(self):
        self.limits(60, 90)
        out = self.ask(70)
        self.assertEqual(out, {"price": 70, "overlap": True, "value": None, "basis": "limits"})
        self.assertEqual(set(out), {"price", "overlap", "value", "basis"})          # never a limit
        self.limits(90, 60)
        self.assertEqual(self.ask(70), {"price": None, "overlap": False, "value": None, "basis": None})
        self.assertNotIn("held", self.ask(70))

    def test_it_is_not_the_midpoint(self):
        """With the old rule a seller who knew its 60 read the buyer's limit as 2 x price - 60."""
        self.limits(60, 90)
        self.assertEqual(self.ask(70)["price"], 70)                                # the reference, not 75
        hits = 0
        for hi in range(70, 131, 3):
            self.limits(60, hi)
            price = self.ask(200)["price"]                                         # a reference above the overlap
            self.assertTrue(60 <= price <= hi)
            hits += 2 * price - 60 == hi
        self.assertLess(hits, 4)                                                   # the old inversion fails

    def test_a_price_does_not_identify_the_other_limit(self):
        """Several limits of the buyer give the seller the very same price, and the margin is secret per vault:
        what a seller learns is a band, never the number."""
        prices = {}
        for hi in range(80, 101):
            self.limits(60, hi)
            prices.setdefault(self.ask(200)["price"], []).append(hi)
        self.assertTrue(any(len(v) > 1 for v in prices.values()), prices)          # one price, several limits
        seen = set()
        for i in range(40):                                                        # other vaults: other margins
            with tempfile.TemporaryDirectory() as d:
                v = private.Vault(Path(d) / "p")
                v.data = {"t01": {"SAL-09": {"min": 60}}, "t02": {"SAL-09": {"max": 100}}}
                p = quotes.Quoter(v).quote("t01", "t02", "SAL-09", 200, 40)["price"]
                self.assertTrue(70 <= p <= 90, p)                                  # the middle half of the overlap
                seen.add(p)
        self.assertGreater(len(seen), 1)                                           # not computable without the key

    def test_value_and_one_sided_limits(self):
        self.limits(60, 90, v_sell=100, v_buy=80)
        self.assertIs(self.ask(70)["value"], False)                                # the buyer values it less
        self.limits(60, 90, v_sell=50, v_buy=80)
        self.assertIs(self.ask(70)["value"], True)
        with self.v.lock:
            self.v.data["t02"] = {}
        self.assertEqual(self.ask(70)["overlap"], None)                            # one limit: it is not looked at
        self.assertEqual(self.ask(45), {"price": 45, "overlap": None, "value": None, "basis": None})   # whatever the price
        out = self.ask(45, bid=85)                                                 # a public bid never stands in for it
        self.assertEqual((out["price"], out["overlap"], out["basis"]), (45, None, None))

    def test_a_refusal_is_held_so_limits_cannot_be_walked(self):
        self.limits(95, 90)
        no = self.q.at(100).quote("t01", "t02", "SAL-09", 200, 40)
        self.assertEqual((no["price"], no["overlap"]), (None, False))
        self.limits(80, 90)                                                        # the seller steps down to find 90
        self.assertEqual(self.q.at(105).quote("t01", "t02", "SAL-09", 200, 40), no)
        self.assertEqual(self.q.at(100 + quotes.HOLD_TICKS).quote("t01", "t02", "SAL-09", 200, 40)["overlap"], True)
        again = [self.q.quote("t01", "t02", "SAL-09", 200, 40)["price"] for _ in range(5)]
        self.assertEqual(len(set(again)), 1)                                       # asking again: the same price
        self.assertIs(self.q.overlap("t01", "t02", "SAL-09"), True)
        self.assertIsNone(self.q.overlap("t01", "t03", "SAL-09"))

    def test_the_matcher_uses_the_vault_blindly(self):
        self.limits(60, 90)
        sh = sheets(agent("t01", sale=["SAL-09"]), agent("t02", wants=["SAL-09"]))
        m = M.find(sh, CAT, gate=self.v.gate, quote=self.q.quote)[0]
        self.assertEqual((m["price"], m["basis"]), (70, "limits"))
        numbers = [v for v in m.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        for secret in (60, 90):                                                    # no field carries a limit
            self.assertNotIn(secret, numbers)
        self.assertEqual(m["recipe"]["buyer"]["body"]["give"], {"cash": 70})
        self.limits(95, 90)
        self.assertEqual(len(M.find(sh, CAT, quote=self.q.at(50).quote)), 1)       # an answer stands for the hold:
        self.assertEqual(M.find(sh, CAT, quote=self.q.at(quotes.HOLD_TICKS + 1).quote), [])   # moving a limit asks nothing new


class StatesTest(unittest.TestCase):
    def test_the_table(self):
        self.assertEqual(set(D.MOVES), set(D.STATES))
        for final in D.DONE_STATES:
            for to in D.STATES:
                self.assertFalse(D.can_move(final, to), (final, to))               # nothing leaves a final state
        for frm, to in (("proposed", "accepted"), ("accepted", "offer_on_v07"), ("proposed", "proposed"),
                        ("settled", "proposed"), ("expired", "settled"), ("passed", "accepted"),
                        ("settled_elsewhere", "settled"), ("nope", "settled"), ("proposed", "nope")):
            self.assertFalse(D.can_move(frm, to), (frm, to))
        for frm, to in (("proposed", "offer_on_v07"), ("offer_on_v07", "accepted"), ("accepted", "settled"),
                        ("offer_on_v07", "settled"), ("offer_on_v07", "proposed"), ("accepted", "expired"),
                        ("proposed", "passed"), ("accepted", "settled_elsewhere")):
            self.assertTrue(D.can_move(frm, to), (frm, to))

    def test_a_forbidden_move_does_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            deals = D.Deals(Path(d) / "m.json")
            rec = {"id": "m-0000000001", "state": "settled", "seller": "t01", "buyer": "t02", "ref": "SAL-09",
                   "kind": "sale"}
            events = []
            for to in D.STATES:
                self.assertFalse(deals._move(rec, to, 5, events))
            self.assertEqual((rec["state"], events), ("settled", []))


class DealsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "matches.json"
        self.d = D.Deals(self.path)
        self.cands = M.find(sheets(agent("t01", spares=["SAL-09"]), agent("t02", wants=["SAL-09"])), CAT)
        self.d.sync(self.cands, 10, [])
        self.m = self.d.live()[0]

    def tearDown(self):
        self.dir.cleanup()

    def test_settled_on_our_venue_keeps_the_games_ids(self):
        log = [listed(12, "t02", "t01", "SAL-09", 65, oid=20311, venue="v07")]
        self.assertEqual([e["state"] for e in self.d.sync(self.cands, 12, log)], ["offer_on_v07"])
        log.append(settled(13, "t01", "t02", "SAL-09", 65, venue="v07", sid=1054))
        ev = self.d.sync(self.cands, 13, log)
        self.assertEqual([(e["state"], e["price"]) for e in ev], [("settled", 65)])
        rec = self.d.get(self.m["id"])
        self.assertEqual((rec["offer"], rec["settlement"], rec["settled_venue"]), (20311, 1054, "v07"))
        self.assertEqual((self.d.funnel()["settled"], self.d.funnel()["offer_on_v07"], self.d.funnel()["proposed"]), (1, 1, 1))
        self.assertEqual([(c["state"], c["settlement"], c["venue"]) for c in self.d.closed], [("settled", 1054, "v07")])

    def test_closed_on_another_venue_is_a_trade_we_lost(self):
        log = [listed(11, "t02", "t01", "SAL-09", 65, oid=7, venue="rastro")]
        self.assertEqual(self.d.sync(self.cands, 11, log), [])                      # not our venue: still proposed
        self.assertEqual(self.d.get(self.m["id"])["state"], "proposed")
        self.assertEqual([(n["kind"], n["team"], n["venue"]) for n in self.d.notes], [("wrong_venue", "t02", "rastro")])
        log.append(settled(12, "t01", "t02", "SAL-09", 65, venue="rastro", sid=9))
        ev = self.d.sync(self.cands, 12, log)
        self.assertEqual([e["state"] for e in ev], ["settled_elsewhere"])
        rec = self.d.get(self.m["id"])
        self.assertEqual((rec["state"], rec["settled_venue"]), ("settled_elsewhere", "rastro"))
        self.assertEqual((self.d.funnel()["settled"], self.d.funnel()["settled_elsewhere"]), (0, 1))
        self.assertEqual(self.d.sync(self.cands, 13, log), [])                      # final: not proposed again now
        with self.assertRaises(PlazaError) as e:
            self.d.message(self.m["id"], "t02", True, {"action": "counter", "price": 60})
        self.assertEqual(e.exception.code, "closed")

    def test_an_offer_that_runs_out_sends_the_match_back(self):
        log = [listed(12, "t02", "t01", "SAL-09", 65, oid=3, venue="v07")]
        self.d.sync(self.cands, 12, log)
        self.d.message(self.m["id"], "t01", True, {"action": "accept"})
        self.assertEqual(self.d.get(self.m["id"])["state"], "accepted")
        ev = self.d.sync(self.cands, 12 + D.OFFER_LIFE + 1, log)
        rec = self.d.get(self.m["id"])
        self.assertEqual(([e["state"] for e in ev], rec["state"], rec["offer"], rec["agreed"]),
                         (["proposed"], "proposed", None, []))

    def test_an_agent_reports_its_offer_and_only_the_feed_is_believed(self):
        mid = self.m["id"]
        good = {"id": 20311, "maker": "t02", "to": "t01", "venue": "v07", "ref": "SAL-09", "price": 65, "created_tick": 11}
        rec, ev, ok = self.d.report_offer(mid, "t02", 20311, None)                  # the feed has not shown it yet
        self.assertEqual((rec["state"], ev, ok, rec["reported_offer"]["id"]), ("proposed", [], False, 20311))
        for bad, code in (({**good, "venue": "rastro"}, "conflict"), ({**good, "maker": "t03"}, "conflict"),
                          ({**good, "to": "t05"}, "conflict"), ({**good, "ref": "LAT-06"}, "conflict")):
            with self.assertRaises(PlazaError) as e:
                self.d.report_offer(mid, "t02", 20311, bad)
            self.assertEqual((e.exception.status, e.exception.code), (409, code))
        with self.assertRaises(PlazaError) as e:
            self.d.report_offer(mid, "t02", 20311, {**good, "venue": "rastro"})
        self.assertIn('"venue": "v07"', e.exception.message)                        # the answer says how to fix it
        with self.assertRaises(PlazaError) as e:
            self.d.report_offer(mid, "t03", 20311, good)
        self.assertEqual(e.exception.code, "not_a_party")
        for junk in (True, "20311", 0, -4, 10 ** 12, 1.5, None, [1]):
            with self.assertRaises(PlazaError) as e:
                self.d.report_offer(mid, "t02", junk, good)
            self.assertEqual(e.exception.status, 400)
        rec, ev, ok = self.d.report_offer(mid, "t02", 20311, good)
        self.assertEqual((rec["state"], rec["offer"], rec["price"], ok, [x["state"] for x in ev]),
                         ("offer_on_v07", 20311, 65, True, ["offer_on_v07"]))
        self.assertEqual(self.d.report_offer(mid, "t02", 20311, good)[1:], ([], True))   # twice: the same answer

    def test_a_second_accept_or_pass_changes_nothing(self):
        mid = self.m["id"]
        self.assertIsNone(self.d.repeated(mid, "t01", {"action": "accept"}))
        self.d.message(mid, "t01", True, {"action": "accept"})
        self.assertEqual(self.d.repeated(mid, "t01", {"action": "accept"})["id"], mid)
        self.assertIsNone(self.d.repeated(mid, "t01", {"action": "counter", "price": 70}))
        self.assertIsNone(self.d.repeated(mid, "t09", {"action": "accept"}))        # not a party: the usual 403
        self.d.message(mid, "t02", True, {"action": "pass"})
        self.assertEqual(self.d.repeated(mid, "t02", {"action": "pass"})["state"], "passed")
        self.assertEqual(self.d.repeated(mid, "t01", {"action": "accept"})["state"], "passed")
        self.assertEqual(len(self.d.get(mid)["messages"]), 2)

    def test_a_paused_team_keeps_its_live_matches(self):
        self.assertEqual(self.d.sync([], 11, [], paused_teams={"t02"}), [])
        self.assertEqual(len(self.d.live()), 1)
        self.d.sync([], 12, [])                                                     # the sheets changed: withdrawn
        self.assertEqual(self.d.live(), [])

    def test_a_write_cut_half_way_does_not_lose_the_matches(self):
        self.d.message(self.m["id"], "t01", True, {"action": "counter", "price": 80})   # a second save: a .bak exists
        self.assertTrue(safe.bak(self.path).exists())
        self.path.write_text('{"matches": {"m-00')                                  # the process died while writing
        again = D.Deals(self.path)
        self.assertEqual([r["id"] for r in again.live()], [self.m["id"]])
        self.path.unlink()
        self.assertEqual(len(D.Deals(self.path).live()), 1)                         # no main file at all: the backup
        safe.bak(self.path).write_text("rubbish")
        self.assertEqual(D.Deals(self.path).live(), [])                             # nothing readable: starts empty


class FeedTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "record" / "latest").mkdir(parents=True)
        self.live = root / "live"
        self.live.mkdir()
        self.feed = F.Feed(self.live, root / "record")

    def tearDown(self):
        self.dir.cleanup()

    def events(self, *rows):
        with (self.live / "events.jsonl").open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        self.feed.refresh()

    def sale(self, tick, venue, a, b, ref, price, sid, **extra):
        return {"tick": tick, "type": "settlement", "payload": {"settlement": sid, "venue": venue, "price": price,
                "parties": [a, b], "items": [{"ref": ref, "frm": a, "to": b}], **extra}}

    def test_team_sales_on_every_venue_reach_the_log_with_their_id(self):
        self.events(self.sale(5, "v07", "t01", "t02", "LAT-03", 20, 1), self.sale(6, "rastro", "t03", "t04", "LAT-03", 30, 2),
                    self.sale(7, None, "pilar", "t05", "LAT-03", 9, 3, persona="pilar"),
                    {"tick": 8, "type": "offer.listed", "payload": {"offer": {
                        "id": 44, "maker": "t03", "to": "t04", "venue": "rastro", "give": {"cash": 30},
                        "want": {"cards": ["LAT-06"]}, "created_tick": 8, "expires_tick": 68}}})
        log = self.feed.venue_log
        self.assertEqual([(e["t"], e["venue"], e.get("id")) for e in log],
                         [("settled", "v07", 1), ("settled", "rastro", 2), ("listed", "rastro", 44)])
        self.assertEqual(self.feed.counts["venue_deals"], 1)                        # only ours counts as ours
        self.assertEqual(self.feed.by_venue(), {"v07": 1, "rastro": 1})
        self.assertEqual(self.feed.traded_pairs(), {frozenset(("t01", "t02"))})
        self.assertEqual(self.feed.offer(44)["venue"], "rastro")
        self.assertIsNone(self.feed.offer(True))
        self.assertIsNone(self.feed.offer(45))

    def test_the_reference_price_is_the_median_of_team_sales(self):
        self.assertEqual(self.feed.team_prices(), {})
        self.events(*[self.sale(5 + i, "rastro", "t01", "t02", "LAT-03", p, i) for i, p in enumerate((10, 30, 12))],
                    self.sale(9, None, "pilar", "t05", "LAT-03", 99, 9, persona="pilar"),
                    self.sale(10, "v07", "t01", "t02", "LAT-06", 20, 10), self.sale(11, "v07", "t01", "t02", "LAT-06", 30, 11))
        self.assertEqual(self.feed.team_prices(), {"LAT-03": 12, "LAT-06": 25})    # the dealer's 99 does not count


class RoutesTest(unittest.TestCase):
    """Through HTTP, with the public sheet of test_server: t09 asks 20 for LAT-06 and t07 bids 20."""
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call

    def connect(self, team):
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": team})
        self.assertEqual(st, 200, s)
        st, a, _ = self.call("POST", "/plaza/api/connect/agent", {"team": team, "code": s["connect_code"]})
        self.assertEqual(st, 200, a)
        (self.record / "threads" / f"th-{team}.json").write_text(json.dumps(      # the proof in the game
            {"id": team, "kind": "team", "messages": [{"sender": team, "text": s["connect_code"]}]}) + "\n")
        self.board.verified_at = 0.0
        token = {"X-Plaza-Token": a["agent_token"]}
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=token)[0], 200)   # seen: the team is proved
        return token

    def event(self, **e):
        with (self.live / "events.jsonl").open("a") as f:
            f.write(json.dumps(e) + "\n")
        self.board.tick_feed()

    def mid(self):
        return self.call("GET", "/plaza/api/matches?team=t07")[1]["matches"][0]["id"]

    def test_my_trades_shows_what_i_give_receive_and_do_next(self):
        t7, t9 = self.connect("t07"), self.connect("t09")
        self.assertEqual(self.call("GET", "/plaza/api/me/trades")[0], 401)
        st, out, _ = self.call("GET", "/plaza/api/me/trades", headers=t7)
        self.assertEqual((st, out["team"], len(out["trades"]), out["counts"]["proposed"]), (200, "t07", 1, 1))
        self.assertEqual(out["trades"][0]["next"]["type"], "decide")       # no limit of its own: nothing goes ahead
        self.board.vault.put("t07", "LAT-06", {"max": 25})
        out = self.call("GET", "/plaza/api/me/trades", headers=t7)[1]
        t = out["trades"][0]
        self.assertEqual((t["your_role"], t["gives"], [c["ref"] for c in t["receives"]], t["cash"], t["mode"], t["order"],
                          t["venue"], t["state"]), ("buyer", [], ["LAT-06"], -20, "auto", None, "v07", "proposed"))
        self.assertEqual((t["next"]["type"], t["next"]["target"]), ("post_offer", "game"))
        self.assertEqual(t["thread"], [])
        self.assertNotIn("basis", t)
        seller = self.call("GET", "/plaza/api/me/trades", headers=t9)[1]["trades"][0]
        self.assertEqual((seller["your_role"], [c["ref"] for c in seller["gives"]], seller["cash"]), ("seller", ["LAT-06"], 20))
        self.assertEqual(self.call("GET", "/plaza/api/me/trades", headers=self.connect("t08"))[1]["trades"], [])

    def test_the_queue_names_our_venue_and_asks_for_the_offer_id(self):
        t7 = self.connect("t07")
        self.board.vault.put("t07", "LAT-06", {"max": 25})
        nxt = self.call("GET", "/plaza/api/agent/next", headers=t7)[1]
        post = next(a for a in nxt["actions"] if a["type"] == "post_offer")
        self.assertEqual(post["request"]["body"]["venue"], "v07")
        self.assertIn("v07", post["why"])
        self.assertEqual((post["then"]["path"], set(post["then"]["body"])), (f"/plaza/api/me/trade/{self.mid()}", {"offer_id"}))
        sync = next(a for a in nxt["actions"] if a["type"] == "sync_cards")
        self.assertEqual(set(sync["request"]["body"]), {"wants", "spares", "for_sale", "have"})

    def test_orders_modes_and_the_reported_offer(self):
        t7, t9, t8 = self.connect("t07"), self.connect("t09"), self.connect("t08")
        url = f"/plaza/api/me/trade/{self.mid()}"
        for body in ({}, {"nope": 1}, {"mode": "fast"}, {"order": "sell"}, {"order": "counter"}, {"order": "counter", "price": "9"},
                     {"order": "counter", "price": 20.5}, {"order": "counter", "price": 99999}, {"order": "accept", "price": 20},
                     {"price": 20}, {"offer_id": "x"}, {"offer_id": True}, {"offer_id": -1}, [1], "x"):
            self.assertEqual(self.call("POST", url, body, t7)[0], 400, body)
        self.assertEqual(self.call("POST", url, {"order": "counter", "price": 5}, t7)[1]["error"], "below_floor")
        self.assertEqual(self.call("POST", url, {"mode": "ask_me"}, t8)[1]["error"], "not_a_party")    # another team
        self.assertEqual(self.call("POST", url, {"mode": "ask_me"})[0], 401)
        self.assertEqual(self.call("POST", "/plaza/api/me/trade/m-ffffffffff", {"mode": "auto"}, t7)[0], 404)
        st, out, _ = self.call("POST", url, {"mode": "ask_me"}, t7)
        self.assertEqual((st, out["agent"]["modes"]), (200, {self.mid(): "ask_me"}))
        st, out, _ = self.call("POST", url, {"order": "counter", "price": 22}, t7)
        self.assertEqual((st, out["agent"]["orders"][self.mid()]["price"]), (200, 22))
        st, out, _ = self.call("POST", url, {"offer_id": 501}, t7)                  # the feed has not shown it
        self.assertEqual((st, out["offer"]["confirmed"], out["state"]), (200, False, "proposed"))
        offer = {"id": 502, "maker": "t07", "to": "t09", "venue": "rastro", "give": {"cash": 20},
                 "want": {"cards": ["LAT-06"]}, "created_tick": 80, "expires_tick": 140}
        self.event(id=1, tick=80, type="offer.listed", payload={"offer": offer})
        st, out, _ = self.call("POST", url, {"offer_id": 502}, t7)                  # on the wrong venue
        self.assertEqual((st, out["error"]), (409, "conflict"))
        self.assertIn("v07", out["message"])
        self.assertEqual(self.call("POST", url, {"offer_id": 502}, t9)[0], 409)     # and not the seller's offer
        self.event(id=2, tick=81, type="offer.listed", payload={"offer": {**offer, "id": 503, "venue": "v07"}})
        st, out, _ = self.call("POST", url, {"offer_id": 503}, t7)
        self.assertEqual((st, out["offer"]["confirmed"], out["state"]), (200, True, "offer_on_v07"))
        self.assertEqual(self.call("POST", url, {"offer_id": 503}, t7)[1]["state"], "offer_on_v07")    # twice
        self.board.vault.put("t09", "LAT-06", {"min": 15})
        nxt = self.call("GET", "/plaza/api/agent/next", headers=t9)[1]
        self.assertIn(("accept_offer", 503), [(a["type"], a.get("offer")) for a in nxt["actions"]])

    def test_a_sale_on_v07_settles_the_match_and_one_elsewhere_is_lost(self):
        admin = {"X-Plaza-Admin": "test-admin-token"}
        t7 = self.connect("t07")
        mid = self.mid()
        self.event(id=3, tick=82, type="settlement", payload={
            "settlement": 1054, "kind": "trade", "venue": "v07", "price": 20, "parties": ["t09", "t07"], "fee": 0,
            "items": [{"ref": "LAT-06", "frm": "t09", "to": "t07"}]})
        st, out, _ = self.call("GET", "/plaza/api/me/trades", headers=t7)
        t = out["trades"][0]
        self.assertEqual((t["id"], t["state"], t["settlement"], t["settled_venue"], t["next"]), (mid, "settled", 1054, "v07", None))
        self.assertEqual(out["counts"]["settled"], 1)
        st, perf, _ = self.call("GET", "/plaza/admin/api/performance", headers=admin)
        self.assertEqual((st, perf["ours"]["settled"], perf["ours"]["volume"], perf["funnel"]["settled"]), (200, 1, 20, 1))
        self.assertEqual(perf["feed"]["venue_deals"], 2)
        self.assertEqual([(r["team"], r["deals"]) for r in perf["per_team"] if r["deals"]], [("t07", 1), ("t09", 1)])
        st, again, _ = self.call("POST", f"/plaza/api/match/{mid}/message", {"action": "accept"}, t7)
        self.assertEqual((st, again["repeated"], again["match"]["state"]), (200, True, "settled"))
        self.assertEqual(self.call("POST", f"/plaza/api/match/{mid}/message", {"action": "counter", "price": 30}, t7)[0], 409)
        self.assertEqual(self.call("GET", "/plaza/api/stats")[1]["matches_settled"], 1)

    def test_market_card_and_stats(self):
        st, mk, h = self.call("GET", "/plaza/api/market")
        self.assertEqual((st, mk["total"], mk["venue"], h["Access-Control-Allow-Origin"]), (200, 2, "v07", "*"))
        row = next(c for c in mk["cards"] if c["ref"] == "LAT-06")
        self.assertEqual((row["holders"], row["seekers"], row["best_ask"], row["best_bid"], row["matches"], row["name"]),
                         (1, 1, 20, 20, 1, "La Chulapa"))
        self.assertNotIn("you", row)
        self.assertEqual(mk["sets"], [{"id": "LAT", "name": "La Latina", "color": "#F2A541"}])
        last = next(c for c in mk["cards"] if c["ref"] == "LAT-03")
        self.assertEqual((last["last_price"], last["last_tick"]), (20, 5))
        self.assertEqual(self.call("GET", "/plaza/api/market?rarity=common")[1]["total"], 1)
        self.assertEqual(self.call("GET", "/plaza/api/market?set=XXX")[1]["total"], 0)
        self.assertEqual(self.call("GET", "/plaza/api/market?rarity=shiny")[0], 400)
        mine = self.call("GET", "/plaza/api/market", headers=self.connect("t07"))[1]
        self.assertEqual(next(c for c in mine["cards"] if c["ref"] == "LAT-06")["you"], "want")
        st, card, _ = self.call("GET", "/plaza/api/card/LAT-03")
        self.assertEqual((st, card["deals"], card["reference_price"]),
                         (200, [{"tick": 5, "price": 20, "venue": "v07", "seller": "t01", "buyer": "t02"}], 20))
        card = self.call("GET", "/plaza/api/card/LAT-06")[1]
        self.assertEqual([(m["seller"], m["buyer"], m["state"]) for m in card["possible_matches"]], [("t09", "t07", "proposed")])
        self.assertIsNone(card["reference_price"])                                  # no trade between teams yet
        self.assertNotIn("you", card)
        self.assertEqual(self.call("GET", "/plaza/api/card/LAT-99")[0], 404)
        self.assertEqual(self.call("GET", "/plaza/api/card/LAT-13")[0], 404)        # hidden cards stay hidden
        st, stats, _ = self.call("GET", "/plaza/api/stats")
        self.assertEqual((st, stats["venue"], stats["deals"], stats["fee_bps"], stats["teams"], stats["matches_live"],
                          stats["teams_connected"]), (200, "v07", 1, 0, 17, 1, 1))

    def test_rubbish_gets_a_4xx_and_the_server_goes_on(self):
        t7 = self.connect("t07")
        mid = self.mid()
        self.srv.RequestHandlerClass.budget.take = lambda *a, **k: True          # this test is not about the budget
        deep = "x"
        for _ in range(40):
            deep = {"a": [deep]}
        junk = [None, True, 0, -1, 1e308, "x" * 5000, [], {}, deep, {"order": deep}, {"offer_id": 1e30},
                {"mode": ["auto"]}, {"order": {"a": 1}, "price": []}, {"action": None}, {"action": "accept", "price": "NaN"}]
        for path in (f"/plaza/api/me/trade/{mid}", f"/plaza/api/match/{mid}/message", "/plaza/api/me/trade/nope",
                     "/plaza/api/match/m-zzzzzzzzzz/message"):
            for body in junk:
                st, out, _ = self.call("POST", path, body, t7)
                self.assertTrue(400 <= st < 500, (path, body, st))
                self.assertNotIn("Traceback", json.dumps(out))
            for method in ("PUT", "DELETE", "PATCH"):
                self.assertIn(self.call(method, path, {"mode": "auto"}, t7)[0], (404, 405))
        bad = [b"\xff\xfe{", b'{"mode": "auto"', b"[" * 5000, b'{"offer_id": 1' + b"0" * 400 + b"}"]
        for raw in bad:
            import urllib.error
            import urllib.request
            req = urllib.request.Request(self.base + f"/plaza/api/me/trade/{mid}", data=raw, method="POST",
                                         headers={"Content-Type": "application/json", **t7})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    st = r.status
            except urllib.error.HTTPError as e:
                st = e.code
                e.close()
            self.assertTrue(400 <= st < 500, (raw[:20], st))
        for path in ("/plaza/api/market?set=%00", "/plaza/api/card/..%2f..", "/plaza/api/me/trades?session=" + "a" * 500,
                     "/plaza/api/stats?team=<script>"):
            self.assertTrue(400 <= self.call("GET", path)[0] < 500, path)
        self.assertEqual(self.call("GET", "/plaza/api/health")[0], 200)             # still serving
        self.assertEqual(self.call("GET", "/plaza/api/me/trades", headers=t7)[1]["trades"][0]["state"], "proposed")


if __name__ == "__main__":
    unittest.main()
