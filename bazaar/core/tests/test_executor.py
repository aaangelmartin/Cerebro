import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from bazaar.core import executor, rails
from bazaar.core.ledger import Ledger
from bazaar.core.types import Action
from bazaar.gateway import GameError

OFFER = {"id": 7, "maker": "t3", "to": None, "venue": "rastro", "thread": None, "status": "open",
         "give": {"cash": 0, "assets": [{"id": 50, "ref": "LAV-09"}], "types": []},
         "want": {"cash": 40, "assets": [], "types": []}}


class FakeGW:
    def __init__(self, gets=None, fail=None):
        self.gets, self.fail, self.calls = gets or {}, fail, []

    def get(self, path, **params):
        self.calls.append(("GET", path, None, None))
        if path not in self.gets:
            raise GameError("not_found", path, 404)
        return self.gets[path]

    def _write(self, method, path, body=None, broker_key=None):
        self.calls.append((method, path, body, broker_key))
        if self.fail:
            raise self.fail
        return {"ok": True, "path": path}

    def post(self, path, body=None, broker_key=None):
        return self._write("POST", path, body, broker_key)

    def patch(self, path, body=None, broker_key=None):
        return self._write("PATCH", path, body, broker_key)

    def delete(self, path):
        return self._write("DELETE", path)


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.lg = Ledger(self.dir.name)
        self.ctx = NS(tick=12, control={"armed": True}, ledger=self.lg, budget={})
        self.stop = mock.patch.object(rails, "STOP_FILE", Path(self.dir.name) / "STOP")
        self.stop.start()

    def tearDown(self):
        self.stop.stop()
        self.dir.cleanup()

    def run_(self, action, gw):
        return executor.execute(action, gw, None, self.ctx)

    def test_mapping(self):
        cases = [
            (Action("open_thread", {"with": "abuela", "topic": {"buy": {"pack": "p"}}}, "dealers"),
             ("POST", "/api/threads", {"with": "abuela", "topic": {"buy": {"pack": "p"}}})),
            (Action("thread_message", {"thread": 4, "price": 22, "text": "hola"}, "dealers"),
             ("POST", "/api/threads/4/messages", {"text": "hola", "price": 22})),
            (Action("close_thread", {"thread": 4}, "dealers"), ("POST", "/api/threads/4/close", {})),
            (Action("post_offer", {"venue": "rastro", "give": {"assets": [1]}, "want": {"cash": 9}}, "market"),
             ("POST", "/api/offers", {"venue": "rastro", "give": {"assets": [1]}, "want": {"cash": 9}})),
            (Action("cancel_offer", {"offer": 3}, "market"), ("DELETE", "/api/offers/3", None)),
            (Action("duel_message", {"duel": 9, "price": 60, "days": 2, "text": "t"}, "duels"),
             ("POST", "/api/duels/9/messages", {"text": "t", "price": 60, "days": 2})),
            (Action("venue_open", {"name": "board", "fee_bps": 0, "mechanism": "board"}, "broker"),
             ("POST", "/api/venues", {"name": "board", "fee_bps": 0, "fee_per_card": 0, "rules": {"mechanism": "board"},
                                      "description": ""})),
            (Action("venue_patch", {"venue": "v1", "fee_bps": 100}, "broker"), ("PATCH", "/api/venues/v1", {"fee_bps": 100})),
        ]
        for action, (method, path, body) in cases:
            gw = FakeGW()
            out = self.run_(action, gw)
            self.assertEqual(out.status, "sent", action.kind)
            self.assertEqual(gw.calls[-1][:3], (method, path, body), action.kind)
        self.assertEqual(len(self.lg.tail("outcomes")), len(cases))

    def test_accept_rereads_and_records_spend(self):
        gw = FakeGW({"/api/venues/rastro/offers": {"offers": [dict(OFFER)]}})
        out = self.run_(Action("accept_offer", {"offer": 7, "expect": dict(OFFER)}, "market"), gw)
        self.assertEqual(out.status, "sent")
        self.assertEqual(gw.calls[0][:2], ("GET", "/api/venues/rastro/offers"))
        self.assertEqual(gw.calls[-1][:2], ("POST", "/api/offers/7/accept"))
        self.assertEqual(self.lg.spend_last_hour(), 40)
        self.assertEqual(self.lg.deals_with("t3"), 1)

    def test_accept_of_a_public_bid_made_by_a_blocked_team_is_vetoed(self):
        # The order names only the offer: its maker is known on the re-read (RET-03 went to t06 this way).
        bid = {k: v for k, v in OFFER.items() if k != "maker"}
        gw = FakeGW({"/api/venues/rastro/offers": {"offers": [{**bid, "maker": "T06"}]}})
        self.ctx.control["blocked_teams"] = ["t06"]
        out = self.run_(Action("accept_offer", {"offer": 7, "expect": bid}, "market"), gw)
        self.assertEqual((out.status, out.response["rail"]), ("vetoed", "blocked_team"))
        self.assertFalse(any(c[0] == "POST" for c in gw.calls))
        self.ctx.control["blocked_teams"] = []
        self.assertEqual(self.run_(Action("accept_offer", {"offer": 7, "expect": bid}, "market"), gw).status, "sent")

    def test_accept_vetoed_when_offer_changed(self):
        changed = {**OFFER, "want": {"cash": 400}}
        gw = FakeGW({"/api/venues/rastro/offers": {"offers": [changed]}, "/api/me/offers": {"offers": []}})
        out = self.run_(Action("accept_offer", {"offer": 7, "expect": dict(OFFER)}, "market"), gw)
        self.assertEqual((out.status, out.response["rail"]), ("vetoed", "fresh"))
        self.assertFalse(any(c[0] == "POST" for c in gw.calls))

    def test_accept_offer_found_in_thread(self):
        o = {**OFFER, "maker": "abuela", "venue": None, "thread": 24}
        gw = FakeGW({"/api/threads/24": {"id": 24, "messages": [{"offer": {**o, "id": 6, "status": "cancelled"}},
                                                                {"offer": o}]}})
        out = self.run_(Action("accept_offer", {"offer": 7, "expect": o}, "dealers"), gw)
        self.assertEqual(out.status, "sent")

    def test_duel_accept(self):
        duel = {"duel": 9, "status": "live", "rival_offer": {"id": 1, "price": 130, "tick": 5}, "your_offer": None}
        gw = FakeGW({"/api/duels": {"duels": [duel]}})
        ok = self.run_(Action("duel_accept", {"duel": 9, "expect": {"id": 1, "price": 130}}, "duels"), gw)
        self.assertEqual(ok.status, "sent")
        gw = FakeGW({"/api/duels": {"duels": [duel]}})
        bad = self.run_(Action("duel_accept", {"duel": 9, "expect": {"id": 1, "price": 120}}, "duels"), gw)
        self.assertEqual(bad.status, "vetoed")

    def test_errors_become_outcomes(self):
        out = self.run_(Action("close_thread", {"thread": 1}, "dealers"),
                        FakeGW(fail=GameError("wait_for_tick", "later", 429, {"next_tick_in": 2.0})))
        self.assertEqual((out.status, out.response["error"], out.response["next_tick_in"]), ("refused", "wait_for_tick", 2.0))
        out = self.run_(Action("close_thread", {"thread": 1}, "dealers"), FakeGW(fail=GameError("upstream", "", 502)))
        self.assertEqual(out.status, "error")
        out = self.run_(Action("close_thread", {}, "dealers"), FakeGW())
        self.assertEqual((out.status, out.response["error"]), ("error", "bad_action"))
        out = self.run_(Action("close_thread", {"thread": 1}, "dealers"), FakeGW(fail=RuntimeError("x")))
        self.assertEqual(out.status, "error")

    def test_disarmed(self):
        self.ctx.control["armed"] = False
        gw = FakeGW()
        out = self.run_(Action("close_thread", {"thread": 1}, "dealers"), gw)
        self.assertEqual(out.status, "vetoed")
        self.assertEqual(gw.calls, [])

    def test_broker_key(self):
        bfile = Path(self.dir.name) / "broker.json"
        with mock.patch.object(executor, "BROKER_FILE", bfile):
            out = self.run_(Action("broker_match", {"sell": 1, "buy": 2, "price": 5}, "broker"), FakeGW())
            self.assertEqual((out.status, out.response["error"]), ("error", "no_broker_key"))
            bfile.write_text(json.dumps({"broker_key": "bk-1"}))
            gw = FakeGW()
            out = self.run_(Action("broker_match", {"sell": 1, "buy": 2, "price": 5}, "broker"), gw)
            self.assertEqual(out.status, "sent")
            self.assertEqual(gw.calls[-1], ("POST", "/api/broker/matches", {"sell": 1, "buy": 2, "price": 5}, "bk-1"))

    def test_venue_open_timeout_alerts_and_recovers_key(self):
        class SlowGW(FakeGW):
            def post(self, path, body=None, broker_key=None, timeout=None):
                self.calls.append(("POST", path, body, timeout))
                raise GameError("timeout", f"POST {path} took over {timeout}s")

        live = Path(self.dir.name) / "live"
        bfile = live / "broker.json"
        gw = SlowGW({"/api/me": {"id": "t10", "venue": "v9", "broker_key": "bk-secret", "cash": 100},
                     "/api/venues": {"venues": [{"id": "v9", "name": "board", "rules": {"mechanism": "board"}, "bond": 250}]}})
        notices = []
        from bazaar.broker import venue
        with mock.patch.object(executor.config, "LIVE", live), mock.patch.object(venue, "BROKER_FILE", bfile), \
                mock.patch("bazaar.lab.store.write_notice", lambda kind, text, **kw: notices.append((kind, text))):
            out = self.run_(Action("venue_open", {"name": "board"}, "broker"), gw)
        self.assertEqual((out.status, out.response["error"]), ("error", "timeout"))
        self.assertEqual(gw.calls[0][3], executor.VENUE_OPEN_TIMEOUT_S)          # 30 s for this call only
        self.assertEqual([c[1] for c in gw.calls[1:]], ["/api/me", "/api/venues"])
        rows = [json.loads(x) for x in (live / "alerts.jsonl").read_text().splitlines()]
        self.assertEqual((rows[0]["kind"], rows[0]["venue"], rows[0]["recovered"]), ("venue_key_maybe_lost", "v9", True))
        self.assertNotIn("bk-secret", (live / "alerts.jsonl").read_text())
        self.assertEqual(json.loads(bfile.read_text())["broker_key"], "bk-secret")
        self.assertEqual(len(notices), 1)

    def test_venue_open_network_error_without_venue_alerts(self):
        gw = FakeGW({"/api/me": {"id": "t10"}, "/api/venues": []}, fail=GameError("network", "reset"))
        live = Path(self.dir.name) / "live2"
        from bazaar.broker import venue
        with mock.patch.object(executor.config, "LIVE", live), \
                mock.patch.object(venue, "BROKER_FILE", live / "broker.json"):
            out = self.run_(Action("venue_open", {"name": "board"}, "broker"), gw)
        self.assertEqual(out.status, "error")
        row = json.loads((live / "alerts.jsonl").read_text().splitlines()[0])
        self.assertEqual((row["venue"], row["has_key"]), (None, False))
        self.assertIn("ALERTA", row["text"])

    def test_noop(self):
        gw = FakeGW()
        self.assertEqual(self.run_(Action("noop", {}, "lab"), gw).status, "sent")
        self.assertEqual(gw.calls, [])


if __name__ == "__main__":
    unittest.main()
