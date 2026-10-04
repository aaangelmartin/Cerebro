"""The dashboard's own conversation with a dealer: the game routes it uses, the manual-thread guard and
the accept check (never lose value, never pass the cash reserve or the per-deal cap)."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bazaar.api import dealerchat, server

HDR = {"X-Dashboard": "1", "Content-Type": "application/json"}


class FakeGame:
    def __init__(self, cash=200):
        self.calls, self.threads, self.values = [], [], {"LAV-11": 288.0}
        self.me = {"id": "t10", "cash": cash, "unlocked": ["banco"],
                   "assets": [{"id": 7, "ref": "MAL-02", "rarity": "common", "your_value": 4.0},
                              {"id": 8, "ref": "MAL-02", "rarity": "common", "your_value": 13.0}]}

    def get(self, path, **params):
        if path == "/api/me":
            return self.me
        if path == "/api/me/threads":
            return {"threads": self.threads}
        if path == "/api/dealers":
            return {"personas": [{"id": "banco", "name": "Don Ernesto", "level": 5, "status": "active",
                                  "kind": "dealer", "menu": {"deals_per_team_per_hour": 4}}]}
        return {}

    def value(self, ref):
        return self.values.get(ref)

    def post(self, path, body=None):
        self.calls.append((path, body))
        if path == "/api/threads":
            t = {"id": 50, "kind": "persona", "with": body["with"], "topic": body["topic"], "status": "open",
                 "messages": [], "standing_offers": []}
            self.threads.append(t)
            return t
        return {"ok": True}

    def offer(self, price, card="LAV-11", status="open"):
        o = {"id": 900, "maker": "banco", "to": "t10", "thread": 50, "status": status, "final": False,
             "give": {"cash": 0, "assets": [], "types": [f"card:{card}"]}, "want": {"cash": price, "assets": [], "types": []}}
        self.threads[0]["messages"].append({"id": 1, "tick": 3, "sender": "banco", "text": "My price.", "offer": o})
        self.threads[0]["standing_offers"] = [o]


class DealerChatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name) / "live"
        self.lab = Path(self.tmp.name) / "lab"
        self.live.mkdir()
        self.lab.mkdir()
        self.game = FakeGame()
        self.srv = server.make_server(0, self.live, self.lab)
        self.srv.RequestHandlerClass.dealer_gw = self.game
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def manual(self):
        return json.loads((self.live / "control.json").read_text()).get("manual_threads")

    def test_writes_need_the_dashboard_header(self):
        self.assertEqual(self.req("/dealer-chat/send", {"dealer": "banco", "text": "hola"})[0], 403)
        self.assertEqual(self.game.calls, [])

    def test_send_opens_the_thread_marks_it_manual_and_posts(self):
        code, out = self.req("/dealer-chat/send", {"dealer": "banco", "text": "Good evening, Don Ernesto.",
                                                   "side": "buy", "item": "lav-11", "price": 150}, HDR)
        self.assertEqual((code, out["thread"], out["opened"]), (200, 50, True))
        self.assertEqual(self.game.calls, [
            ("/api/threads", {"with": "banco", "topic": {"buy": {"card": "LAV-11"}}}),
            ("/api/threads/50/messages", {"text": "Good evening, Don Ernesto.", "price": 150})])
        self.assertEqual(self.manual(), [50])
        code, out = self.req("/dealer-chat/send", {"dealer": "banco", "text": "And now?"}, HDR)   # same thread
        self.assertEqual((out["opened"], self.game.calls[-1]), (False, ("/api/threads/50/messages", {"text": "And now?"})))

    def test_sell_topic_uses_our_cheapest_copy_and_packs_go_by_id(self):
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "x", "side": "sell", "item": "MAL-02"}, HDR)
        self.assertEqual(self.game.calls[0][1]["topic"], {"sell": {"assets": [7]}})
        self.assertEqual(dealerchat._topic("buy", "sobre_oro", {}), {"buy": {"pack": "sobre_oro"}})
        self.assertEqual(self.req("/dealer-chat/send", {"dealer": "abuela", "text": "x"}, HDR)[0], 400)  # no topic

    def test_state_shows_the_thread_and_the_value_check(self):
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "x", "side": "buy", "item": "LAV-11"}, HDR)
        self.game.offer(110)
        code, st = self.req("/dealer-chat?dealer=banco")
        self.assertEqual((code, st["thread"]["id"], st["thread"]["manual"], len(st["thread"]["messages"])), (200, 50, True, 1))
        self.assertEqual((st["check"]["value_get"], st["check"]["value_give"], st["check"]["gain"], st["check"]["blocked"]),
                         (288.0, 110.0, 178.0, None))

    def test_accept_needs_confirm_then_accepts(self):
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "x", "side": "buy", "item": "LAV-11"}, HDR)
        self.game.offer(110)
        code, out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900}, HDR)
        self.assertEqual((out["accepted"], out["needs_confirm"], out["check"]["gain"]), (False, True, 178.0))
        self.assertNotIn("/api/offers/900/accept", [c[0] for c in self.game.calls])
        code, out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900, "confirm": True}, HDR)
        self.assertTrue(out["accepted"])
        self.assertEqual(self.game.calls[-1], ("/api/offers/900/accept", {}))

    def test_accept_refuses_a_loss_the_reserve_and_the_per_deal_cap(self):
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "x", "side": "buy", "item": "LAV-11"}, HDR)
        for price, cash, card, word in ((190, 200, "LAV-11", "reserva"), (150, 400, "LAV-11", "tope por trato"),
                                        (100, 400, "MAL-99", "no conocemos"), (100, 400, "LAV-11", None)):
            self.game.me["cash"] = cash
            self.game.threads[0]["messages"] = []
            self.game.offer(price, card)
            out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900, "confirm": True}, HDR)[1]
            if word is None:
                self.assertTrue(out["accepted"])
            else:
                self.assertFalse(out["accepted"])
                self.assertIn(word, out["check"]["blocked"])
        self.game.values["LAV-11"] = 80.0                                   # worth less than the price: a loss
        self.game.threads[0]["messages"] = []
        self.game.offer(100)
        out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900, "confirm": True}, HDR)[1]
        self.assertIn("perdemos valor", out["check"]["blocked"])
        self.assertEqual([c[0] for c in self.game.calls].count("/api/offers/900/accept"), 1)

    def test_a_page_card_may_cost_up_to_the_price_the_team_set(self):
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "x", "side": "buy", "item": "LAV-11"}, HDR)
        self.game.values["LAV-11"] = 80.0
        self.game.me["cash"] = 400
        self.req("/control", {"page_buys": {"LAV-11": 90}}, HDR)
        self.game.threads[0]["messages"] = []
        self.game.offer(100)                                                # above the price we set: still a loss
        out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900, "confirm": True}, HDR)[1]
        self.assertIn("perdemos valor", out["check"]["blocked"])
        self.game.threads[0]["messages"] = []
        self.game.offer(90)
        out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900, "confirm": True}, HDR)[1]
        self.assertTrue(out["accepted"])
        self.game.threads[0]["messages"] = []
        self.game.values["MAL-09"] = 80.0
        self.game.offer(90, "MAL-09")                                       # the dealer switched the card: not the one we set
        out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900, "confirm": True}, HDR)[1]
        self.assertFalse(out["accepted"])
        self.assertIn("perdemos valor", out["check"]["blocked"])
        self.assertEqual(self.req("/control", {"page_buys": {"LAV-11": 500}}, HDR)[0], 400)

    def test_a_pack_is_never_bought_by_hand(self):
        self.game.me["cash"] = 900
        code, out = self.req("/dealer-chat/send", {"dealer": "banco", "text": "400", "side": "buy",
                                                   "item": "sobre_oro", "price": 400}, HDR)
        self.assertEqual(code, 400)                                         # a priced bid for a pack: refused
        self.assertEqual(self.game.calls, [])
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "Buenas tardes.", "side": "buy",
                                       "item": "sobre_oro"}, HDR)            # talking is still allowed
        o = {"id": 900, "maker": "banco", "to": "t10", "thread": 50, "status": "open", "final": False,
             "give": {"cash": 0, "assets": [], "types": ["pack:sobre_oro"]}, "want": {"cash": 150, "assets": [], "types": []}}
        self.game.threads[0]["standing_offers"] = [o]
        out = self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 900, "confirm": True}, HDR)[1]
        self.assertFalse(out["accepted"])
        self.assertIn("sobres", out["check"]["blocked"])
        self.assertNotIn("/api/offers/900/accept", [c[0] for c in self.game.calls])
        o["want"]["cash"] = 0                                               # a pack given for nothing is taken
        chk = dealerchat.check(o, self.game, self.game.me, {})
        self.assertNotIn("sobres", str(chk["blocked"]))

    def test_control_takes_the_no_packs_switch(self):
        code, out = self.req("/control", {"no_packs": True}, HDR)
        self.assertEqual((code, out["no_packs"]), (200, True))
        self.assertEqual(self.req("/control", {"no_packs": "yes"}, HDR)[0], 400)

    def test_a_stale_offer_id_is_refused(self):
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "x", "side": "buy", "item": "LAV-11"}, HDR)
        self.game.offer(100)
        self.assertEqual(self.req("/dealer-chat/accept", {"dealer": "banco", "offer": 899, "confirm": True}, HDR)[0], 400)

    def test_close_and_release_drop_the_guard(self):
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "x", "side": "buy", "item": "LAV-11"}, HDR)
        self.assertEqual(self.req("/dealer-chat/release", {"thread": 50}, HDR)[1]["manual_threads"], [])
        self.req("/dealer-chat/send", {"dealer": "banco", "text": "again"}, HDR)
        self.assertEqual(self.manual(), [50])
        out = self.req("/dealer-chat/close", {"thread": 50}, HDR)[1]
        self.assertEqual((out["closed"], out["manual_threads"], self.game.calls[-1]), (50, [], ("/api/threads/50/close", {})))

    def test_state_forgets_manual_threads_that_closed(self):
        self.req("/control", {"manual_threads": [41]}, HDR)
        self.assertEqual(self.req("/dealer-chat?dealer=banco")[1]["manual_threads"], [])
        self.assertEqual(self.manual(), [])


if __name__ == "__main__":
    unittest.main()
