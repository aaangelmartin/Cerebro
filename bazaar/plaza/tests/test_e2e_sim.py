"""The market end to end: fake agents that use only the public API, a fake game, the real server on a temp folder.

A hard assertion here is something that must never break. A `finding` is a gap against CONTRACT.md that another
fork still owes: it is listed in the skip reason (and fails the test with PLAZA_E2E_STRICT=1, which is how the
final pass runs: `python -m bazaar.plaza.e2e.run`)."""
import json
import os
import re
import threading
import unittest
from pathlib import Path

from bazaar.plaza import deals as D
from bazaar.plaza import routes as R
from bazaar.plaza import server as S
from bazaar.plaza.e2e.rig import SECRET_RX, Rig

STRICT = os.environ.get("PLAZA_E2E_STRICT") == "1"
FIXTURES = Path(R.__file__).parent / "web" / "fixtures"


def live(method: str, path: str) -> bool:
    return any(r.method == method and r.path == path and r.live for r in R.ROUTES)


class E2E(unittest.TestCase):
    def setUp(self):
        self.rig = Rig().start()
        self.findings: list[str] = []
        self.addCleanup(self.rig.stop)

    def finding(self, ok: bool, owner: str, text: str) -> bool:
        if not ok:
            self.findings.append(f"[{owner}] {text}")
        return ok

    def close(self):
        """Last line of every test: open findings fail in strict mode and are a visible skip otherwise."""
        if self.findings:
            msg = "open findings: " + " | ".join(self.findings)
            if STRICT:
                self.fail(msg)
            self.skipTest(msg)

    def pair(self, ref="SAL-10", lo=60, hi=90, ask=70):
        seller = self.rig.agent("t01", for_sale=[{"ref": ref, "price": ask, "min": lo}], have=[ref, "SAL-01"])
        buyer = self.rig.agent("t02", wants=[{"ref": ref, "max": hi}])
        return seller, buyer

    def state(self, a="t01", b="t02", ref=None):
        m = self.rig.match_of(a, b, ref)
        return m["state"] if m else None

    def healthy(self):
        s, out, _ = self.rig.call("GET", "/plaza/api/health", client="10.0.0.99")
        self.assertEqual(s, 200, out)


class HappyPath(E2E):
    def test_two_agents_close_a_sale_on_v07_and_it_settles(self):
        seller, buyer = self.pair()
        s, st, _ = self.rig.call("GET", "/plaza/api/connect/status", session=seller.session)
        self.assertTrue(st["verified"] and st["agent_called"], st)
        self.rig.run(6, until=lambda: self.state() == "settled")
        m = self.rig.match_of("t01", "t02")
        self.assertEqual(m["state"], "settled")
        states = [h["state"] for h in m["history"]]
        self.assertIn("offer_on_v07", states)
        self.assertEqual(states[-1], "settled")
        self.assertIn("SAL-10", self.rig.game.hand("t02"))
        self.assertNotIn("SAL-10", self.rig.game.hand("t01"))
        self.assertTrue(60 <= m["price"] <= 90)
        # every game request named our venue and was sent by the agents, never by the market
        offers = [r for r in self.rig.game.requests if r[2] == "/api/offers"]
        self.assertEqual([(r[0], r[3]["venue"], r[3]["to"]) for r in offers], [("t02", "v07", "t01")])
        self.assertEqual(self.rig.game.venue_stats["trades"], 1)
        # the panel and the public counters saw it
        s, over, _ = self.rig.call("GET", "/plaza/admin/api/overview", admin=True)
        self.assertEqual(s, 200)
        self.assertEqual(over["funnel"]["deals_on_venue"], 1)
        if live("GET", "/api/stats"):
            s, stats, _ = self.rig.call("GET", "/plaza/api/stats")
            self.finding(s == 200 and json.dumps(stats).count("1") > 0, "B2", f"/api/stats after a deal: {s} {stats}")
        if live("GET", "/admin/api/performance"):
            s, perf, _ = self.rig.call("GET", "/plaza/admin/api/performance", admin=True)
            self.finding(s == 200 and "75" in json.dumps(perf) or s == 200 and str(m["price"]) in json.dumps(perf),
                         "B2", f"performance does not show the settled trade: {s}")
        if live("GET", "/api/me/trades"):
            s, tr, _ = buyer.api("GET", "/plaza/api/me/trades")
            self.finding(s == 200 and m["id"] in json.dumps(tr), "B2", f"/api/me/trades misses the settled match: {s}")
        if live("GET", "/api/me/activity"):
            s, act, _ = buyer.api("GET", "/plaza/api/me/activity")
            kinds = {a.get("kind") for a in (act.get("activity") or act.get("items") or [])} if s == 200 else set()
            self.finding({"connect", "settle"} <= kinds, "B1/B2", f"activity kinds after a trade: {sorted(kinds)}")
        self.close()

    def test_a_swap_closes_card_for_card(self):
        a = self.rig.agent("t03", spares=["LAV-09"], wants=["MAL-09"], have=["LAV-09"])
        b = self.rig.agent("t04", spares=["MAL-09"], wants=["LAV-09"], have=["MAL-09"])
        self.rig.run(6, until=lambda: self.rig.game.hand("t03") == ["MAL-09"])
        self.assertEqual((self.rig.game.hand("t03"), self.rig.game.hand("t04")), (["MAL-09"], ["LAV-09"]))
        self.assertEqual(self.rig.game.cash["t03"], 500)      # card for card, or two sales at the same price
        on_v07 = [r for r in self.rig.game.requests if r[2] == "/api/offers"]
        self.assertTrue(on_v07 and all(r[3]["venue"] == "v07" for r in on_v07))
        kinds = {m["kind"] for m in self.rig.board.deals.all() if m["state"] == "settled"}
        self.finding(kinds == {"swap"}, "B2", f"two teams that each hold what the other misses are paired as "
                                              f"{sorted(kinds)} (two cash sales), not as one swap")
        self.rig.run(2)
        live_now = [m for m in self.rig.board.deals.all() if m["state"] in D.LIVE_STATES]
        self.assertEqual(live_now, [])                        # nothing is proposed for cards that already moved
        del a, b
        self.close()

    def test_four_agents_two_trades_no_cross_talk(self):
        self.pair()
        self.rig.agent("t05", for_sale=[{"ref": "RET-09", "price": 60, "min": 50}], have=["RET-09"])
        self.rig.agent("t06", wants=[{"ref": "RET-09", "max": 75}])            # nobody is excluded from the market
        self.rig.run(8, until=lambda: self.state() == "settled" and self.state("t05", "t06") == "settled")
        self.assertEqual((self.state(), self.state("t05", "t06")), ("settled", "settled"))
        self.assertEqual(self.rig.game.venue_stats["trades"], 2)
        self.assertIsNone(self.rig.match_of("t01", "t06"))


class NoBadMatches(E2E):
    def test_limits_that_do_not_overlap_are_never_proposed(self):
        self.pair(lo=100, hi=50, ask=120)
        self.rig.run(3)
        self.assertIsNone(self.rig.match_of("t01", "t02"))
        self.assertEqual(self.rig.game.venue_stats["trades"], 0)

    def test_the_host_is_never_a_party_and_cannot_connect(self):
        s, out, _ = self.rig.call("POST", "/plaza/api/connect/start", {"team": "t10"})
        self.assertEqual(s, 403, out)
        self.pair()
        self.rig.refresh()
        for m in self.rig.board.deals.all():
            self.assertNotIn("t10", (m["seller"], m["buyer"]))

    def test_a_paused_team_gets_no_new_match(self):
        if not live("POST", "/api/me/settings"):
            self.skipTest("POST /api/me/settings is not live yet")
        seller = self.rig.agent("t01", for_sale=[{"ref": "SAL-10", "price": 70, "min": 60}], have=["SAL-10"])
        s, out, _ = seller.api("POST", "/plaza/api/me/settings", {"paused": True})
        self.assertEqual(s, 200, out)
        self.rig.agent("t02", wants=[{"ref": "SAL-10", "max": 90}])
        self.rig.run(2)
        self.finding(self.rig.match_of("t01", "t02") is None, "B2", "a paused team still got a new match")
        self.close()

    def test_a_trade_that_would_destroy_value_is_not_proposed(self):
        """SCORING.md 3: the buyer values the card less than the seller does; settling it would cost us points."""
        self.rig.agent("t01", for_sale=[{"ref": "SAL-10", "price": 70, "min": 60, "value": 95}], have=["SAL-10"])
        self.rig.agent("t02", wants=[{"ref": "SAL-10", "max": 90, "value": 40}])
        self.rig.run(2)
        self.finding(self.rig.match_of("t01", "t02") is None, "B2",
                     "matcher proposes a sale where the buyer's value (40) is below the seller's (95): SCORING.md 3")
        self.close()

    def test_the_suggested_price_does_not_give_away_the_midpoint(self):
        """SCORING.md 8: a price at the exact middle of the two private limits lets each side compute the other's."""
        self.pair(lo=60, hi=90, ask=70)
        self.rig.refresh()
        m = self.rig.match_of("t01", "t02")
        self.assertIsNotNone(m)
        self.finding(m["price"] != 75, "B2", "suggested price is the exact midpoint of the private limits (60, 90)")
        self.close()


class RoughAgents(E2E):
    def test_an_agent_that_dies_half_way_is_waited_for_and_then_finishes(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        seller.step()
        buyer.step()                                          # the offer is on v07
        seller.alive = False
        self.rig.run(3)
        self.assertEqual(self.state(), "offer_on_v07")
        self.assertEqual(self.rig.game.venue_stats["trades"], 0)
        seller.alive = True
        self.rig.run(4, until=lambda: self.state() == "settled")
        self.assertEqual(self.state(), "settled")

    def test_repeating_everything_changes_nothing_more(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        q = buyer.queue()
        self.assertTrue(q["actions"], q)
        first = q["actions"][0]
        buyer.step()
        again = buyer.queue()
        self.assertNotIn(first["id"], [a["id"] for a in again["actions"]])      # done is done
        for _ in range(2):                                    # a second ack of the same id is accepted and harmless
            s, out, _ = buyer.api("POST", "/plaza/api/agent/ack", {"id": first["id"], "status": "done"})
            self.assertEqual(s, 200, out)
        seller.step()
        self.rig.run(5, until=lambda: self.state() == "settled")
        self.assertEqual(self.state(), "settled")
        self.assertEqual(len([r for r in self.rig.game.requests if r[2] == "/api/offers"]), 1)
        self.assertEqual(self.rig.game.venue_stats["trades"], 1)
        m = self.rig.match_of("t01", "t02")
        s, out, _ = seller.api("POST", f"/plaza/api/match/{m['id']}/message", {"action": "accept"})
        self.finding(s == 200, "B2", f"a second accept on a settled match answers {s} "
                                     f"{out.get('error') if isinstance(out, dict) else ''}, not the current state (6.2)")
        self.assertEqual(self.state(), "settled")             # nothing leaves a final state
        self.close()

    def test_both_sides_accepting_at_once_keeps_one_consistent_match(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        mid = self.rig.match_of("t01", "t02")["id"]
        codes, lock = [], threading.Lock()

        def hit(agent):
            s, _, _ = agent.api("POST", f"/plaza/api/match/{mid}/message", {"action": "accept"})
            with lock:
                codes.append(s)

        threads = [threading.Thread(target=hit, args=(a,)) for a in (seller, buyer) * 6]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(c in (200, 409, 429) for c in codes), codes)
        saved = json.loads((self.rig.game.live / "plaza_matches.json").read_text())
        rec = saved["matches"][mid]
        self.assertIn(rec["state"], D.STATES)
        self.assertLessEqual(len(set(rec.get("agreed") or [])), 2)
        self.rig.run(5, until=lambda: self.state() == "settled")
        self.assertEqual(self.state(), "settled")
        self.assertEqual(self.rig.game.venue_stats["trades"], 1)

    def test_the_server_restarts_in_the_middle_of_a_trade(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        seller.step()
        buyer.step()
        self.rig.refresh()
        self.assertEqual(self.state(), "offer_on_v07")
        mid = self.rig.match_of("t01", "t02")["id"]
        self.rig.restart()
        self.assertEqual(seller.queue()["team"], "t01")       # the token survived
        m = self.rig.match_of("t01", "t02")
        self.assertEqual((m["id"], m["state"]), (mid, "offer_on_v07"))
        self.rig.run(4, until=lambda: self.state() == "settled")
        self.assertEqual(self.state(), "settled")
        self.assertEqual(self.rig.game.venue_stats["trades"], 1)

    def test_a_broken_store_file_does_not_take_the_market_down(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        self.assertEqual(self.state(), "proposed")
        mid = self.rig.match_of("t01", "t02")["id"]
        seller.step()                                         # a second write of every store: now there is a
        buyer.queue()                                         # previous copy to fall back to
        self.rig.game.advance()
        self.rig.refresh()
        self.rig.halt()
        for name in ("plaza_matches.json", "plaza.json", "plaza_agentq.json", "plaza_connect.json"):
            path = self.rig.game.live / name
            if path.exists():
                path.write_text(path.read_text()[: max(1, path.stat().st_size // 2)])       # a write cut half way
        self.rig.start()
        self.healthy()
        s, _, _ = self.rig.call("GET", "/plaza/api/teams")
        self.assertEqual(s, 200)
        s, _, _ = self.rig.call("GET", "/plaza/admin/api/overview", admin=True)
        self.assertEqual(s, 200)
        backups = [n for n in ("plaza_matches.json", "plaza.json", "plaza_connect.json")
                   if (self.rig.game.live / (n + ".bak")).exists()]
        self.finding(len(backups) == 3, "B1/B2", f"stores keep no .bak copy to load after a cut write (6.2 Files): "
                                                 f"only {backups or 'none'}")
        self.finding(self.rig.match_of("t01", "t02") is not None and self.rig.match_of("t01", "t02")["id"] == mid,
                     "B2", "the live match is lost after a cut write of plaza_matches.json")
        s, q, _ = seller.api("GET", "/plaza/api/agent/next")
        self.finding(s == 200, "B1", f"the agent's token is lost after a cut write of plaza_connect.json ({s})")
        self.close()

    def test_a_deal_closed_on_another_venue_is_told_apart(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        mid = self.rig.match_of("t01", "t02")["id"]
        oid = self.rig.game.post_offer("t02", {"venue": "rastro", "give": {"cash": 75}, "want": {"cards": ["SAL-10"]},
                                               "to": "t01"})["id"]
        self.rig.game.accept("t01", oid, {"assets": [self.rig.game.asset_of("t01", "SAL-10")]})
        try:
            self.rig.run(2)
        except Exception as e:  # noqa: BLE001 - a rebuild that raises freezes the live board: report it and stop
            self.finding(False, "B2/shell", f"Board.rebuild raises {type(e).__name__}({e}) when the deal of a match "
                                            f"is posted on another venue (the 'wrong_venue' event has no 'state')")
            self.close()
        m = self.rig.board.deals.get(mid)
        self.assertNotEqual(m["state"], "settled")            # it never counts as ours
        self.assertEqual(self.rig.game.venue_stats["trades"], 0)
        self.finding(m["state"] == "settled_elsewhere", "B2",
                     f"a match closed on El Rastro stays '{m['state']}', not 'settled_elsewhere' (6.3)")
        self.close()


class Standing(E2E):
    """A matched trade that its maker closes on another venue: a warning, then the ban, and we can lift it."""

    def elsewhere(self, buyer: str, seller: str, ref: str, price: int) -> None:
        oid = self.rig.game.post_offer(buyer, {"venue": "rastro", "give": {"cash": price}, "want": {"cards": [ref]},
                                               "to": seller})["id"]
        self.rig.game.accept(seller, oid, {"assets": [self.rig.game.asset_of(seller, ref)]})
        self.rig.game.advance()
        self.rig.refresh()

    def test_one_warning_then_the_ban_and_the_host_lifts_it(self):
        s1 = self.rig.agent("t01", for_sale=[{"ref": "SAL-10", "price": 70, "min": 60}], have=["SAL-10", "SAL-01"])
        s2 = self.rig.agent("t03", for_sale=[{"ref": "RET-09", "price": 60, "min": 50}], have=["RET-09"])
        buyer = self.rig.agent("t02", wants=[{"ref": "SAL-10", "max": 90}, {"ref": "RET-09", "max": 75}])
        self.rig.refresh()
        self.assertEqual((self.state("t01", "t02"), self.state("t03", "t02")), ("proposed", "proposed"))
        for a in (s1, s2, buyer):
            a.queue()                                          # every agent has read its proposals
        self.assertEqual(buyer.api("GET", "/plaza/api/me")[1]["standing"]["strikes"], 0)

        self.elsewhere("t02", "t01", "SAL-10", 75)             # the buyer posts it on El Rastro and it closes there
        self.assertEqual(self.state("t01", "t02"), "settled_elsewhere")
        st = buyer.api("GET", "/plaza/api/me")[1]["standing"]
        self.assertEqual((st["strikes"], st["limit"], st["banned"], st["last"]["card"], st["last"]["venue"]),
                         (1, 2, False, "SAL-10", "rastro"))
        self.assertEqual(s1.api("GET", "/plaza/api/me")[1]["standing"]["strikes"], 0)      # it only accepted
        q = buyer.queue()
        self.assertEqual(q["actions"][0]["type"], "warning")
        done = buyer.step()                                    # an agent that runs its queue as it comes: no harm
        self.assertIn(("warning", "done", None), done)
        self.assertNotIn("warning", [x["type"] for x in buyer.queue()["actions"]])
        self.assertEqual(buyer.api("GET", "/plaza/api/me/cards")[0], 200)                  # warned, still in

        self.assertEqual(self.state("t03", "t02"), "offer_on_v07")                         # its agent posted it here...
        self.elsewhere("t02", "t03", "RET-09", 60)             # ...and its team closes it on El Rastro all the same
        st, out, _ = buyer.api("GET", "/plaza/api/me/cards")
        self.assertEqual((st, out["error"]), (403, "banned"))
        self.assertEqual(buyer.api("GET", "/plaza/api/agent/next")[0], 403)
        self.assertEqual(buyer.api("PUT", "/plaza/api/team/t02", {"wants": ["LAV-09"]})[0], 403)
        me = buyer.api("GET", "/plaza/api/me")[1]["standing"]
        self.assertEqual((me["banned"], me["strikes"], len(me["evidence"])), (True, 2, 2))
        self.rig.agent("t04", for_sale=[{"ref": "LAV-09", "price": 60, "min": 50}], have=["LAV-09"])
        self.rig.refresh()
        self.assertIsNone(self.rig.match_of("t04", "t02"))     # a banned team is in no new match
        self.assertEqual(s2.api("GET", "/plaza/api/me/cards")[0], 200)                     # nobody else is touched

        st, out, _ = self.rig.call("POST", "/plaza/admin/api/action", {"action": "unban", "team": "t02"}, admin=True)
        self.assertEqual((st, out["standing"]), (200, {"strikes": 1, "limit": 2, "banned": False}))
        self.assertEqual(buyer.api("GET", "/plaza/api/me/cards")[0], 200)
        teams = self.rig.call("GET", "/plaza/admin/api/teams", admin=True)[1]
        ev = next(t for t in teams["strikes"]["teams"] if t["team"] == "t02")["evidence"]
        self.assertEqual([(e["card"], e["venue"], e["role"], e["forgiven"]) for e in ev],
                         [("SAL-10", "rastro", "posted", False), ("RET-09", "rastro", "posted", True)])
        self.healthy()
        self.close()

    def test_an_offer_moved_to_our_venue_before_it_closes_costs_nothing(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        for a in (seller, buyer):
            a.queue()
        oid = self.rig.game.post_offer("t02", {"venue": "rastro", "give": {"cash": 75}, "want": {"cards": ["SAL-10"]},
                                               "to": "t01"})["id"]
        self.rig.refresh()
        self.assertIn("move_offer", [a["type"] for a in buyer.queue()["actions"]])
        self.rig.game.cancel("t02", oid)
        self.rig.run(8, until=lambda: self.state() == "settled")
        self.assertEqual(self.state(), "settled")
        self.assertEqual(buyer.api("GET", "/plaza/api/me")[1]["standing"]["strikes"], 0)
        self.assertEqual(self.rig.board.strikes.view()["teams"], [])
        self.close()


class ClosedAndPaused(E2E):
    def test_our_switch_turns_the_api_off_and_on(self):
        seller, _ = self.pair()
        s, out, _ = self.rig.call("POST", "/plaza/admin/api/action", {"action": "off"}, admin=True)
        self.assertEqual(s, 200, out)
        s, out, _ = seller.publish()
        self.assertEqual((s, out.get("error")), (503, "closed"), out)
        s, h, _ = self.rig.call("GET", "/plaza/api/health")
        self.assertFalse(h["enabled"])
        self.rig.call("POST", "/plaza/admin/api/action", {"action": "on"}, admin=True)
        self.assertEqual(seller.publish()[0], 200)

    def test_doors_closed_then_paused_then_open_again(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        self.rig.game.set_doors("closed")
        self.rig.run(2)
        self.assertEqual(self.rig.game.venue_stats["trades"], 0)
        self.assertIn(self.state(), ("proposed", "offer_on_v07"))
        if live("GET", "/api/status"):
            s, st, _ = self.rig.call("GET", "/plaza/api/status")
            self.finding(s == 200 and st.get("game") == "closed" and st.get("market") == "closed"
                         and st.get("matchmaker") == "waiting", "B1", f"status with doors closed: {s} "
                         f"{ {k: st.get(k) for k in ('game', 'market', 'matchmaker')} if s == 200 else st}")
            self.rig.game.set_doors("open")
            self.rig.game.set_paused(True)
            s, st, _ = self.rig.call("GET", "/plaza/api/status")
            self.finding(s == 200 and st.get("game") == "paused" and st.get("market") == "paused", "B1",
                         f"status with the game paused: {s} { {k: st.get(k) for k in ('game', 'market')} if s == 200 else st}")
            self.rig.game.set_paused(False)
            self.rig.game.stale()
            s, st, _ = self.rig.call("GET", "/plaza/api/status")
            self.finding(s == 200 and st.get("feed") == "stale", "B1", "status.feed is not 'stale' with old recorder files")
            self.rig.game.touch()
        self.rig.game.set_doors("open")
        self.rig.game.set_paused(False)
        for a in (seller, buyer):                             # a failed game action is retried after RETRY_S
            self.rig.board.queue.clock = lambda: __import__("time").time() + 120
        self.rig.run(6, until=lambda: self.state() == "settled")
        self.assertEqual(self.state(), "settled")
        self.close()


class NothingLeaks(E2E):
    SECRETS = ("1741", "1987", "1913", "1999")

    def test_private_limits_never_leave_their_team(self):
        seller = self.rig.agent("t01", for_sale=[{"ref": "SAL-12", "price": 1800, "min": 1741, "value": 1913}],
                                have=["SAL-12", "LAV-07"])
        buyer = self.rig.agent("t02", wants=[{"ref": "SAL-12", "max": 1987, "value": 1999}])
        other = self.rig.agent("t03", wants=["LAV-01"])
        self.rig.refresh()
        m = self.rig.match_of("t01", "t02")
        self.assertIsNotNone(m)
        seller.step()
        buyer.step()
        self.rig.refresh()
        own = {"t01": ("1741", "1913"), "t02": ("1987", "1999")}

        def scan(who: str, text: str, where: str, allowed=()):
            for secret in self.SECRETS:
                if secret not in allowed:                     # as a number of its own, not inside a timestamp
                    self.assertIsNone(re.search(rf"(?<![\d.]){secret}(?![\d.])", text),
                                      f"{secret} leaks to {who} in {where}")

        gets = [r for r in R.ROUTES if r.method == "GET" and r.live and r.path != "/api/floor/stream"]
        for r in gets:
            path = "/plaza" + r.path.replace("{team}", "t01").replace("{ref}", "SAL-12").replace("{match}", m["id"])
            if r.who == "admin":
                s, out, _ = self.rig.call("GET", path, admin=True)
                scan("our panel", json.dumps(out), path)
                continue
            for agent in (seller, buyer, other):
                s, out, _ = agent.api("GET", path)
                mine = own.get(agent.team, ()) if r.who in ("team", "agent") else ()
                scan(agent.team, json.dumps(out), path, allowed=mine)
            s, out, _ = self.rig.call("GET", path, client="10.0.0.50")
            scan("anyone", json.dumps(out), path)
        for path in self.rig.game.live.rglob("*"):            # nothing under data/live either
            if path.is_file() and path.name != "events.jsonl":
                scan("a file", path.read_text(errors="replace"), str(path.name))
        if live("GET", "/api/me/cards"):                      # and its own team does read them back
            s, cards, _ = seller.api("GET", "/plaza/api/me/cards")
            self.finding(s == 200 and "1741" in json.dumps(cards), "B1", "a team cannot read its own limit back")
            s, cards, _ = other.api("GET", "/plaza/api/me/cards")
            self.assertNotIn("LAV-07", json.dumps(cards))     # `have` never leaves /api/me of its own team
        if not self.rig.no_have:                              # LAV-07 is in t01's hand and on none of its lists
            for agent in (buyer, other):
                for path in ("/plaza/api/team/t01", "/plaza/api/teams"):
                    s, out, _ = agent.api("GET", path)
                    if s == 200:
                        self.assertNotIn("LAV-07", json.dumps(out), f"t01's hand leaks in {path}")
                for path in ("/plaza/api/market", "/plaza/api/card/LAV-07"):
                    s, out, _ = agent.api("GET", path)
                    if s != 200:
                        continue
                    row = out if "card/" in path else next((c for c in out.get("cards") or [] if c.get("ref") == "LAV-07"), {})
                    self.assertNotIn("t01", json.dumps({k: v for k, v in row.items() if k != "you"}),
                                     f"t01's hand leaks in {path}")
                    self.assertFalse(row.get("holders") if isinstance(row.get("holders"), int) else False,
                                     f"{path} counts a holder of LAV-07 that only t01's private hand knows")
        self.close()

    def test_one_team_cannot_touch_another(self):
        seller, buyer = self.pair()
        third = self.rig.agent("t03", wants=["LAV-01"])
        self.rig.refresh()
        mid = self.rig.match_of("t01", "t02")["id"]
        s, out, _ = third.api("PUT", "/plaza/api/team/t01", {"wants": ["LAV-02"]})
        self.assertEqual(s, 403, out)
        s, out, _ = third.api("POST", f"/plaza/api/match/{mid}/message", {"action": "pass"})
        self.assertEqual(s, 403, out)
        self.assertEqual(self.state(), "proposed")
        if live("POST", "/api/me/trade/{match}"):
            s, out, _ = third.api("POST", f"/plaza/api/me/trade/{mid}", {"order": "pass"})
            self.assertIn(s, (403, 404), out)
        s, out, _ = self.rig.call("POST", "/plaza/api/agent/ack", {"id": "a-000000000000", "status": "done"},
                                  token="not-a-token")
        self.assertIn(s, (401, 403), out)
        self.finding(s == 401, "B1", f"a bad token answers {s}, the contract says 401 bad_token")
        s, out, _ = self.rig.call("GET", "/plaza/api/agent/next")
        self.assertIn(s, (401, 403), out)
        for path in ("/plaza/admin/api/overview", "/plaza/admin/api/matchmaker", "/plaza/admin/"):
            s, out, _ = self.rig.call("GET", path)
            self.assertEqual(s, 404, path)                    # the panel does not exist without the admin proof
            s, out, _ = self.rig.call("GET", path, token=seller.token)
            self.assertEqual(s, 404, path)
        s, out, _ = self.rig.call("POST", "/plaza/admin/api/action", {"action": "off"}, token=seller.token)
        self.assertEqual(s, 404)
        self.assertTrue(self.rig.call("GET", "/plaza/api/health")[1]["enabled"])
        self.close()

    def test_an_unverified_agent_is_not_taken_for_the_team(self):
        self.rig.agent("t01", for_sale=[{"ref": "SAL-10", "price": 70, "min": 60}], have=["SAL-10"])
        fake = self.rig.agent("t02", wants=[{"ref": "SAL-10", "max": 90}], verify=False)
        self.rig.refresh()
        s, st, _ = self.rig.call("GET", "/plaza/api/connect/status", session=fake.session)
        self.assertFalse(st["verified"])
        m = self.rig.match_of("t01", "t02")
        if m is not None:                                     # whatever it declared, it is not a "declared" match
            s, pub, _ = self.rig.call("GET", f"/plaza/api/match/{m['id']}")
            self.finding(pub.get("confidence") != "declared", "B1",
                         "an agent that never proved its identity in the game publishes a sheet that counts as "
                         "'declared': anyone can start a connection for another team and get matches in its name")
        self.close()


class Rubbish(E2E):
    BODIES = [b"", b"{", b"[]", b"null", b'"text"', b"12", b'{"a":' + b"[" * 2000 + b"]" * 2000 + b"}",
              b"\xff\xfe\x00bad utf8", b'{"team": 7}', b'{"team": "t99"}', b'{"price": 1e400}',
              b'{"price": -5, "action": "counter"}', b'{"price": 99999999999999999999, "action": "counter"}',
              b'{"action": ["accept"]}', b'{"wants": "LAV-01"}', b'{"wants": ["ZZZ-99"]}', b'{"wants": [null, {}, 3]}',
              b'{"for_sale": [{"ref": "SAL-10", "price": "free"}]}', b'{"id": {"$ne": 1}, "status": "done"}',
              b'{"text": "' + b"A" * 5000 + b'"}', b'{"unknown_key": 1}', b'{"action": "off"}',
              b'{"op": "add", "list": "../../etc", "ref": "SAL-10"}', b'{"order": "accept", "price": true}']

    def test_rubbish_gets_a_4xx_and_the_server_keeps_serving(self):
        seller, _ = self.pair()
        self.rig.refresh()
        mid = self.rig.match_of("t01", "t02")["id"]
        bad, n = [], 0
        for r in R.ROUTES:
            if r.method == "GET":
                continue
            path = "/plaza" + r.path.replace("{team}", "t01").replace("{ref}", "SAL-10").replace("{match}", mid)
            for i, body in enumerate(self.BODIES):
                n += 1
                s, out, _ = self.rig.call(r.method, path, raw=body, token=seller.token, admin=r.who == "admin",
                                          client=f"10.{n % 250}.{i}.7")
                text = json.dumps(out) if not isinstance(out, str) else out
                if s >= 500 and s != 503 or SECRET_RX.search(text):
                    bad.append((r.method, r.path, body[:40], s, text[:120]))
                elif s < 400 and body in (b"", b"{", b"[]", b"null", b'"text"', b"12", b"\xff\xfe\x00bad utf8"):
                    self.finding(False, r.owner, f"{r.method} {r.path} answers {s} to the body {body[:20]!r}, "
                                                 f"which is not a JSON object (6.2 Input)")
        self.assertEqual(bad, [])
        self.healthy()
        self.rig.call("POST", "/plaza/admin/api/action", {"action": "on"}, admin=True)
        self.assertEqual(self.state(), "proposed")            # and the match is where it was
        self.close()

    def test_wrong_methods_sizes_and_types(self):
        seller, _ = self.pair()
        for method in ("DELETE", "PATCH", "PUT", "TRACE"):
            s, out, _ = self.rig.call(method, "/plaza/api/teams", client="10.1.1.1")
            self.assertTrue(400 <= s < 500 or s == 501, (method, s))
            self.finding(s < 500, "shell", f"{method} on a route answers {s}, the contract says 4xx")
        s, out, _ = seller.api("PUT", "/plaza/api/team/t01", raw=b'{"wants": ["' + b"A" * 20000 + b'"]}')
        self.assertEqual(s, 413, out)
        s, out, _ = seller.api("PUT", "/plaza/api/team/t01", raw=b'{"wants": ["LAV-01"]}',
                               headers={"Content-Type": "text/plain"})
        self.finding(s == 415, "shell", f"a write without Content-Type: application/json answers {s}, not 415")
        s, out, _ = seller.api("PUT", "/plaza/api/team/t01", {"wants": ["LAV-01"], "surprise": 1})
        self.assertEqual(s, 400, out)
        for path in ("/plaza/../etc/passwd", "/plaza/static/../server.py", "/plaza/static/%2e%2e/server.py",
                     "/plaza/api/team/t01/../../admin/api/overview", "/etc/passwd", "/plaza/static/fixtures/../../x.py"):
            s, out, _ = self.rig.call("GET", path, client="10.1.1.2")
            self.assertEqual(s, 404, path)
            self.assertNotIn("import ", out if isinstance(out, str) else "")
        self.healthy()
        self.close()

    def test_the_request_budget_is_per_client(self):
        seller, buyer = self.pair()
        codes = [seller.api("PUT", "/plaza/api/team/t01", {"wants": ["LAV-01"]})[0]      # far above normal use
                 for _ in range(S.WRITES_PER_MIN + 5)]
        self.assertIn(429, codes)
        self.assertEqual(codes[0], 200)
        s, out, _ = seller.api("PUT", "/plaza/api/team/t01", {"wants": ["LAV-01"]})
        self.assertEqual((s, out.get("error")), (429, "slow_down"), out)
        self.assertEqual(buyer.publish()[0], 200)             # another client is not slowed down
        self.healthy()

    def test_what_a_team_writes_comes_back_as_data_not_as_a_page(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        mid = self.rig.match_of("t01", "t02")["id"]
        evil = '<img src=x onerror=alert(1)><script>alert(2)</script>'
        s, out, _ = seller.api("POST", f"/plaza/api/match/{mid}/message", {"action": "counter", "price": 80, "text": evil})
        self.assertEqual(s, 200, out)
        s, out, h = self.rig.call("GET", f"/plaza/api/match/{mid}")
        self.assertIn("application/json", h.get("Content-Type"))
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
        s, page, h = self.rig.call("GET", "/plaza/?x=" + "%3Cscript%3Ealert(3)%3C/script%3E")
        self.assertEqual(s, 200)
        self.assertNotIn("alert(3)", page)
        self.assertIn("default-src 'self'", h.get("Content-Security-Policy") or "")
        self.assertEqual(h.get("X-Frame-Options"), "DENY")
        del buyer


class Contract(E2E):
    def test_every_live_route_answers_and_has_the_fixture_shape(self):
        seller, buyer = self.pair()
        self.rig.refresh()
        mid = self.rig.match_of("t01", "t02")["id"]
        for r in R.ROUTES:
            if r.method != "GET" or r.path == "/api/floor/stream":
                continue
            path = "/plaza" + r.path.replace("{team}", "t01").replace("{ref}", "SAL-10").replace("{match}", mid)
            kw = {"admin": True} if r.who == "admin" else {"session": seller.session} if r.who == "session" \
                else {"token": seller.token}
            s, out, _ = self.rig.call("GET", path, client=seller.client, **kw)
            if not r.live:
                self.finding(False, r.owner, f"GET {r.path} is still live=False")
                continue
            self.assertNotEqual(s, 404, f"live route GET {r.path} answers 404")
            self.assertLess(s, 500, (r.path, out))
            if r.fixture and s == 200 and isinstance(out, dict):
                want = json.loads((FIXTURES / r.fixture).read_text())
                missing = sorted(set(want) - set(out)) if isinstance(want, dict) else []
                self.finding(not missing, r.owner, f"GET {r.path} lacks the fixture's keys {missing}")
        for r in R.ROUTES:
            if r.method != "GET" and not r.live:
                self.finding(False, r.owner, f"{r.method} {r.path} is still live=False")
        self.close()

    def test_the_queue_only_asks_for_requests_the_api_accepts(self):
        """An agent that sends the queue's request as written must not get a 400."""
        s, start, _ = self.rig.call("POST", "/plaza/api/connect/start", {"team": "t07"})
        s, got, _ = self.rig.call("POST", "/plaza/api/connect/agent", {"team": "t07", "code": start["connect_code"]})
        s, q, _ = self.rig.call("GET", "/plaza/api/agent/next", token=got["agent_token"])
        self.assertEqual((q["verified"], q["actions"]), (False, []))      # before the proof: only "prove it is you"
        self.rig.game.request("t07", "POST", "/api/threads", {"to": self.rig.game_host(), "text": start["connect_code"]})
        self.rig.refresh()
        s, q, _ = self.rig.call("GET", "/plaza/api/agent/next", token=got["agent_token"])
        sync = next((a for a in q["actions"] if a["type"] == "sync_cards"), None)
        self.assertIsNotNone(sync, q)
        body = {k: [] for k in sync["request"]["body"]}       # its keys, with empty lists in place of the hints
        s, out, _ = self.rig.call(sync["request"]["method"], sync["request"]["path"], body, token=got["agent_token"])
        self.finding(s == 200, "B2", f"the sync_cards action names body keys {sorted(body)} and PUT answers {s} "
                                     f"{out.get('message') if isinstance(out, dict) else ''}")
        self.close()

    def test_agents_md_is_served_and_names_the_venue(self):
        for path in ("/plaza/AGENTS.md", "/plaza/agents.md"):
            s, text, h = self.rig.call("GET", path)
            self.finding(s == 200 and isinstance(text, str) and "v07" in text, "D", f"GET {path} answers {s}")
            if s == 200 and isinstance(text, str):
                for r in R.public():
                    if r.live and r.path not in ("/api/openapi.json",):
                        self.finding(r.path.split("{")[0].rstrip("/") in text, "D",
                                     f"AGENTS.md does not name {r.method} {r.path}")
        s, spec, _ = self.rig.call("GET", "/plaza/api/openapi.json")
        self.assertEqual(s, 200)
        listed = set(spec["paths"])
        self.assertLessEqual(listed, {"/plaza" + r.path for r in R.ROUTES if r.live})
        self.assertLessEqual({"/plaza" + r.path for r in R.public() if r.live}, listed)
        self.close()


if __name__ == "__main__":
    unittest.main()
