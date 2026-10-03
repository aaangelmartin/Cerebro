import json
import unittest
import urllib.error
import urllib.request

from bazaar.sim.fake_bazaar import BROKER_KEY, TEAM_KEY, serve


class Client:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method: str, path: str, body=None, key=TEAM_KEY, broker=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if key is not None:
            req.add_header("X-Team-Key", key)
        if broker:
            req.add_header("X-Broker-Key", broker)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)

    def tick(self, n=1):
        return self.post("/sim/tick", {"n": n})


class FakeBazaarTest(unittest.TestCase):
    def setUp(self):
        self.server, self.world, _ = serve(port=0, seed=11, manual=True, duel_at_tick=None, days_duel_at_tick=None,
                                           bench_at_tick=None, vault_at_tick=1000, synthetic_activity=False)
        self.c = Client(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()

    def test_auth(self):
        self.assertEqual(self.c.get("/api/me", key=None)[0], 401)
        st, body = self.c.get("/api/me", key="wrong")
        self.assertEqual((st, body["error"]), (401, "bad_key"))
        self.assertEqual(self.c.get("/api/clock", key=None)[0], 200)  # public read
        st, me = self.c.get("/api/me")
        self.assertEqual(st, 200)
        self.assertEqual(me["cash"], 400)
        rar = [a["rarity"] for a in me["assets"]]
        self.assertEqual((rar.count("common"), rar.count("uncommon"), rar.count("rare")), (11, 3, 1))
        self.assertTrue(all("your_value" in a for a in me["assets"]))
        self.assertEqual(self.c.get("/api/broker/book")[0], 401)

    def test_dealer_thread_accept_settles_next_tick(self):
        st, t = self.c.post("/api/threads", {"with": "abuela", "topic": {"buy": {"rarity": "uncommon", "set": "LAV"}}})
        self.assertEqual(st, 200, t)
        self.assertEqual(self.c.post("/api/threads", {"with": "abuela", "topic": {"buy": {"rarity": "common"}}})[1]["error"],
                         "thread_open")
        st, r = self.c.post(f"/api/threads/{t['id']}/messages", {"text": "Hola, Carmen", "price": 15})
        self.assertEqual(st, 200, r)
        st, r = self.c.post(f"/api/threads/{t['id']}/messages", {"text": "again", "price": 16})
        self.assertEqual((st, r["error"]), (429, "wait_for_tick"))
        self.assertIn("next_tick", r)
        self.c.tick()
        th = self.c.get(f"/api/threads/{t['id']}")[1]
        offer = th["standing_offers"][0]
        price = offer["want"]["cash"]
        self.assertLess(price, t["standing_offers"][0]["want"]["cash"])
        st, r = self.c.post(f"/api/offers/{offer['id']}/accept")
        self.assertEqual(st, 200, r)
        self.assertEqual(self.c.get("/api/me")[1]["cash"], 400)  # not yet
        self.c.tick()
        me = self.c.get("/api/me")[1]
        self.assertEqual(me["cash"], 400 - price)
        state = self.c.get("/sim/state")[1]
        self.assertEqual(state["settled"][0]["price"], price)
        self.assertGreater(state["settled"][0]["capture"], 0)
        feed = self.c.get("/api/feed", key=None)[1]["events"]
        self.assertIn("settlement", {e["type"] for e in feed})

    def test_one_accept_per_tick(self):
        board = self.c.get("/api/venues/rastro/offers")[1]["offers"]
        sells = [o for o in board if o["give"]["assets"] and o["want"]["cash"] <= 150]
        self.assertGreaterEqual(len(sells), 2)
        self.assertEqual(self.c.post(f"/api/offers/{sells[0]['id']}/accept")[0], 200)
        st, r = self.c.post(f"/api/offers/{sells[1]['id']}/accept")
        self.assertEqual((st, r["error"]), (429, "wait_for_tick"))
        n0 = len(self.c.get("/api/me")[1]["assets"])
        self.c.tick()
        self.assertEqual(len(self.c.get("/api/me")[1]["assets"]), n0 + 1)

    def test_rastro_listing_sells(self):
        me = self.c.get("/api/me")[1]
        aid = me["assets"][0]["id"]
        st, o = self.c.post("/api/offers", {"venue": "rastro", "give": {"assets": [aid]}, "want": {"cash": 1}})
        self.assertEqual(st, 200, o)
        self.assertEqual(self.c.post("/api/offers", {"venue": "rastro", "give": {"assets": [aid]}, "want": {"cash": 2}})[0], 409)
        self.assertEqual(self.c.post("/api/offers", {"venue": "rastro", "give": {"assets": [999999]}, "want": {"cash": 2}})[1]["error"],
                         "not_yours")
        for _ in range(40):
            self.c.tick()
            if not any(a["id"] == aid for a in self.c.get("/api/me")[1]["assets"]):
                break
        self.assertFalse(any(a["id"] == aid for a in self.c.get("/api/me")[1]["assets"]))

    def test_duels_and_missing_days(self):
        self.c.post("/sim/control", {"start_duels": {"issues": ["price", "days"], "n": 3}})
        duels = self.c.get("/api/duels")[1]["duels"]
        self.assertEqual(len(duels), 3)
        d = duels[0]
        self.assertIn("your_days_weight", d)
        st, r = self.c.post(f"/api/duels/{d['duel']}/messages", {"text": "hi", "price": 50})
        self.assertEqual((st, r["error"]), (400, "missing_days"))
        st, r = self.c.post(f"/api/duels/{d['duel']}/messages", {"text": "hi", "price": 50, "days": 3})
        self.assertEqual(st, 200, r)
        self.assertEqual(self.c.post(f"/api/duels/{d['duel']}/messages", {"price": 51, "days": 3})[0], 429)
        for _ in range(20):
            self.c.tick()
        done = self.c.get("/api/duels?done=true")[1]["duels"]
        self.assertGreaterEqual(len(done), 3)
        self.assertTrue(all(x["status"] in ("deal", "no_deal") for x in done))

    def test_duel_accept_rival_offer(self):
        self.c.post("/sim/control", {"start_duels": {"n": 6}})
        live = [d for d in self.c.get("/api/duels")[1]["duels"] if d["rival_offer"]]
        self.assertTrue(live)
        d = live[0]
        self.assertEqual(self.c.post(f"/api/duels/{d['duel']}/accept")[0], 200)
        self.c.tick()
        done = [x for x in self.c.get("/api/duels?done=true")[1]["duels"] if x["duel"] == d["duel"]][0]
        self.assertEqual(done["status"], "deal")
        self.assertEqual(done["price"], d["rival_offer"]["price"])
        self.assertIsNotNone(done["result"])

    def test_vault_activation_is_novel(self):
        lv = {x["id"]: x for x in self.c.get("/api/levels")[1]["levels"]}
        self.assertEqual(lv["vault"]["state"], "announced")
        dl = self.c.get("/api/dealers/vault")[1]
        self.assertIsNone(dl["level"])
        self.c.post("/sim/control", {"activate_level": "vault"})
        lv = {x["id"]: x for x in self.c.get("/api/levels")[1]["levels"]}
        self.assertEqual(lv["vault"]["state"], "active")
        types = {(e["type"], e["payload"].get("persona")) for e in self.c.get("/api/feed")[1]["events"]}
        self.assertIn(("persona.open_to_all", "vault"), types)
        self.assertIn(("level.unlocked", "vault"), types)
        st, t = self.c.post("/api/threads", {"with": "vault", "topic": {"buy": {"rarity": "legendary"}}})
        self.assertEqual(st, 200, t)

    def test_limits_change(self):
        self.c.post("/sim/control", {"limits": {"offers_per_team_per_tick": 2}})
        self.assertEqual(self.c.get("/api/clock")[1]["limits"]["offers_per_team_per_tick"], 2)
        types = [e["type"] for e in self.c.get("/api/feed")[1]["events"]]
        self.assertIn("clock.limits_changed", types)
        ids = [a["id"] for a in self.c.get("/api/me")[1]["assets"]]
        for i in range(2):
            self.assertEqual(self.c.post("/api/offers", {"give": {"assets": [ids[i]]}, "want": {"cash": 99}})[0], 200)
        self.assertEqual(self.c.post("/api/offers", {"give": {"assets": [ids[2]]}, "want": {"cash": 99}})[0], 429)

    def test_broker_bench(self):
        self.world.level = 2
        st, v = self.c.post("/api/venues", {"name": "Board 10", "fee_bps": 0, "rules": {"mechanism": "board"}})
        self.assertEqual(st, 200, v)
        self.c.post("/sim/control", {"start_bench": True})
        book = self.c.get("/api/broker/book", broker=BROKER_KEY)[1]
        bench = book["bench_offers"]
        self.assertGreaterEqual(len(bench), 5)  # some traders arrive late
        self.assertTrue(all("-" in o["id"] for o in bench))
        ids = {o["id"] for o in bench}
        sells = [o for o in bench if o["side"] == "sell"]
        buys = [o for o in bench if o["side"] == "buy"]
        self.assertTrue(sells and buys and ids)
        s, b = min(sells, key=lambda o: o["want"]["cash"]), max(buys, key=lambda o: o["give"]["cash"])
        ask, bid = s["want"]["cash"], b["give"]["cash"]
        st, r = self.c.post("/api/broker/matches", {"sell": s["id"], "buy": b["id"], "price": max(ask, bid) + 50},
                            broker=BROKER_KEY)
        self.assertEqual(st, 409)  # outside the quotes
        if bid >= ask:
            st, r = self.c.post("/api/broker/matches", {"sell": s["id"], "buy": b["id"], "price": (ask + bid) // 2},
                                broker=BROKER_KEY)
            self.assertEqual(st, 200, r)
        self.c.tick(17)
        hist = self.c.get("/sim/state")[1]["bench"]["history"]
        self.assertEqual(len(hist), 1)
        self.assertGreaterEqual(hist[0]["efficiency"], 0)

    def test_schedule_and_leaderboard(self):
        sch = self.c.get("/api/schedule")[1]
        self.assertIn("upcoming", sch)
        self.assertTrue(any(e["action"] == "level" for e in sch["upcoming"]))
        self.c.tick(5)
        lb = self.c.get("/api/leaderboard")[1]
        self.assertIn("t10", lb["teams"])
        self.assertEqual(len(lb["teams"]), 18)


if __name__ == "__main__":
    unittest.main()
