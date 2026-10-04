"""Private limits stay with their team (not us, not our bot), and the agent queue tells an agent what to send."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from bazaar.plaza import agentq as Q
from bazaar.plaza import matcher as M
from bazaar.plaza import private as P
from bazaar.plaza import server as S
from bazaar.plaza.store import PlazaError
from bazaar.plaza.tests import test_server as T
from bazaar.plaza.tests.test_connect_deals import FlowTest
from bazaar.plaza.tests.test_matcher import CAT, sheet, sheets

REPO = Path(__file__).resolve().parents[3]
def leaks(blob, secret: str) -> bool:
    """The number on its own (not four digits inside a timestamp)."""
    blob = blob.decode("utf-8", errors="ignore") if isinstance(blob, bytes) else blob
    return bool(re.search(rf"(?<![\d.]){secret}(?![\d.])", blob))


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.v = P.Vault(Path(self.dir.name) / "private")

    def tearDown(self):
        self.dir.cleanup()

    def test_encrypted_at_rest_and_owner_only(self):
        self.v.put("t09", "SAL-09", {"min": 1771, "value": 1991})
        folder = Path(self.dir.name) / "private"
        blob = (folder / "limits.bin").read_bytes()
        for word in (b"1771", b"1991", b"SAL-09", b"t09", b"min"):
            self.assertNotIn(word, blob)
        self.assertEqual(oct(folder.stat().st_mode)[-3:], "700")
        for name in ("limits.bin", "key"):
            self.assertEqual(oct((folder / name).stat().st_mode)[-3:], "600", name)
        again = P.Vault(folder)
        self.assertEqual(again.get("t09"), {"SAL-09": {"min": 1771, "value": 1991}})
        (folder / "key").write_bytes(b"x" * 32)                        # another key reads nothing
        self.assertEqual(P.Vault(folder).get("t09"), {})
        with self.assertRaises(ValueError):
            P.unseal(b"k" * 32, blob)

    def test_blind_gate(self):
        g = self.v.gate
        self.assertEqual(g("t01", "t02", "SAL-09", 60), (60, None))                 # no limits: untouched
        self.v.put("t01", "SAL-09", {"min": 50})
        self.assertEqual(g("t01", "t02", "SAL-09", 60), (60, None))                 # one side: it is not looked at,
        self.assertEqual(g("t01", "t02", "SAL-09", 45), (45, None))                 # whatever the price: nothing to search
        self.v.put("t02", "SAL-09", {"max": 70})
        self.assertEqual(g("t01", "t02", "SAL-09", 45), (45, True))                 # both: they meet; the price is not moved
        self.assertEqual(g("t01", "t02", "SAL-09", 1999), (1999, True))             # and never decides the answer
        self.v.put("t02", "SAL-09", {"max": 49})
        self.assertEqual(g("t01", "t02", "SAL-09", 60), (None, False))              # no overlap: no proposal
        self.assertEqual(self.v.flags("t01"), {"SAL-09": True})
        self.v.put("t01", "SAL-09", {"min": None})
        self.assertEqual((self.v.get("t01"), self.v.flags("t01")), ({}, {}))
        self.assertIs(self.v.within("t02", "SAL-09", "buyer", 49), True)
        self.assertIs(self.v.within("t02", "SAL-09", "buyer", 50), False)
        self.assertIsNone(self.v.within("t01", "SAL-09", "seller", 50))             # no limit of its own: not a yes

    def test_matcher_only_proposes_inside_the_overlap(self):
        sh = sheets(sheet("t01", sale=[{"ref": "SAL-09", "price": 90}]), sheet("t02", wants=["SAL-09"]))
        self.v.put("t01", "SAL-09", {"min": 60})
        self.v.put("t02", "SAL-09", {"max": 80})
        m = M.find(sh, CAT, gate=self.v.gate)[0]
        self.assertEqual(m["basis"], "limits")
        self.assertTrue(60 < m["price"] < 80, m["price"])                           # inside, never on a limit
        self.v.put("t02", "SAL-09", {"max": 55})
        self.v._quoter.kept.clear()                                                 # once the answer given has run its hold
        self.assertEqual(M.find(sh, CAT, gate=self.v.gate), [])
        self.assertEqual(M.find(sh, CAT, strict=False)[0]["price"], 90)             # without the vault: public data only
        self.assertEqual(M.find(sh, CAT), [])                                       # and nothing says both gain: no match

    def test_split_and_validation(self):
        body, priv = P.split({"wants": ["LAV-07", {"ref": "RET-03", "max": 30, "value": 45}],
                              "spares": [{"ref": "SAL-01", "min": 8}], "for_sale": [{"ref": "SAL-09", "price": 60, "min": 50}]})
        self.assertEqual(body, {"wants": ["LAV-07", "RET-03"], "spares": ["SAL-01"], "for_sale": [{"ref": "SAL-09", "price": 60}]})
        self.assertEqual(priv, {"RET-03": {"max": 30, "value": 45}, "SAL-01": {"min": 8}, "SAL-09": {"min": 50}})
        for bad in ({"wants": [{"ref": "RET-03", "min": 3}]}, {"for_sale": [{"ref": "SAL-09", "max": 3}]},
                    {"wants": [{"ref": "RET-03", "max": -1}]}, {"wants": [{"ref": "RET-03", "max": True}]},
                    {"spares": [{"ref": "SAL-01", "price": 3}]}):
            with self.assertRaises(PlazaError):
                P.split(bad)


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.now = [5000.0]
        self.q = Q.AgentQ(Path(self.dir.name) / "q.json", clock=lambda: self.now[0])
        self.m = {"id": "m-0123456789", "kind": "sale", "seller": "t09", "buyer": "t07", "ref": "LAT-06", "price": 20,
                  "state": "proposed", "agreed": [], "offer": None, "venue": "v07",
                  "recipe": M.recipe("t09", "t07", "LAT-06", 20)}

    def tearDown(self):
        self.dir.cleanup()

    def types(self, team, m=None, ok=True, declared=4990.0):
        out = self.q.build(team, [m or self.m], lambda ref, role, price: ok, declared, 7)
        return [a["type"] for a in out["actions"]], out

    def test_auto_mode_walks_the_deal(self):
        t, out = self.types("t07", declared=None)
        self.assertEqual(t, ["sync_cards", "post_offer"])                       # ordered: cards first
        offer = out["actions"][1]["request"]
        self.assertEqual((offer["target"], offer["method"], offer["path"]), ("game", "POST", "/api/offers"))
        self.assertEqual(offer["body"], {"venue": "v07", "give": {"cash": 20}, "want": {"cards": ["LAT-06"]}, "to": "t09"})
        self.assertEqual(self.types("t09")[0], ["agree"])
        on = {**self.m, "state": "offer_on_v07", "offer": 900, "offer_maker": "t07"}
        t, out = self.types("t09", on)
        self.assertEqual(t, ["accept_offer", "confirm"])
        self.assertEqual(out["actions"][0]["request"]["path"], "/api/offers/900/accept")
        self.assertEqual(out["actions"][0]["request"]["body"], {"assets": ["<your asset id of LAT-06>"]})
        t, out = self.types("t07", on)
        self.assertEqual((t, out["waiting"][0]["match"]), ([], self.m["id"]))

    def test_a_match_the_host_forced_is_always_the_agents_call(self):
        forced = {**self.m, "forced": True, "basis": "forced"}
        for team in ("t07", "t09"):                             # inside its limits, price nobody else chose: still decide
            t, out = self.types(team, forced)
            self.assertEqual(t, ["decide"], team)
            self.assertIn("by hand", out["actions"][0]["why"])
        self.assertEqual(self.types("t07", {**forced, "agreed": ["t07"]})[0], ["post_offer"])   # once it said yes

    def test_ack_done_failed_and_retry(self):
        _, out = self.types("t07")
        aid = out["actions"][0]["id"]
        for bad in (("x", "done"), (aid, "maybe"), (None, "done")):
            with self.assertRaises(PlazaError):
                self.q.ack("t07", *bad)
        self.q.ack("t07", aid, "failed", "the game said 409")
        self.assertEqual(self.types("t07")[0], [])                              # not again right away
        self.now[0] += Q.RETRY_S + 1
        self.assertEqual(self.types("t07")[0], ["post_offer"])
        self.q.ack("t07", aid, "failed")
        self.now[0] += Q.RETRY_S + 1
        self.q.ack("t07", aid, "failed")
        self.now[0] += Q.RETRY_S + 1
        t, out = self.types("t07")
        self.assertEqual((t, out["failed"][0]["id"], out["failed"][0]["note"]), ([], aid, None))   # given up, and shown
        self.q.ack("t09", self.types("t09")[1]["actions"][0]["id"], "done")
        self.assertEqual(self.types("t09")[0], [])

    def test_limits_ask_me_and_human_orders(self):
        self.assertEqual(self.types("t07", ok=False)[0], ["decide"])            # outside its own limit: never posts
        self.q.set_mode("t07", "ask_me", self.m["id"])
        t, out = self.types("t07")
        self.assertEqual((t, out["waiting"][0]["why"]), ([], "ask_me: waiting for your human"))
        self.q.order("t07", self.m["id"], "counter", 15)
        t, out = self.types("t07")
        self.assertEqual((t, out["actions"][0]["request"]["body"]), (["counter"], {"action": "counter", "price": 15}))
        self.q.ack("t07", out["actions"][0]["id"], "done")
        self.assertEqual(self.types("t07")[0], [])                              # the order is spent
        self.q.order("t07", self.m["id"], "accept")
        self.assertEqual(self.types("t07", ok=False)[0], ["post_offer"])        # the human said yes
        self.q.order("t07", self.m["id"], "pass")
        self.assertEqual(self.types("t07")[0], ["pass"])
        for bad in (("steal", None), ("counter", None), ("counter", -3), ("counter", True)):
            with self.assertRaises(PlazaError):
                self.q.order("t07", self.m["id"], *bad)
        with self.assertRaises(PlazaError):
            self.q.set_mode("t07", "yolo")
        self.q.set_mode("t09", "ask_me")
        self.assertEqual(self.types("t09")[0], [])


class PrivateFlowTest(FlowTest):
    """Through HTTP: a team's limits are read by that team only."""
    test_connection_flow_end_to_end = test_host_expiry_and_reconnect_through_http = None
    test_match_thread_from_proposal_to_settlement = test_art_blocked_teams_and_hidden_lines = None
    test_matchmaker_panel_is_ours_only = None

    def verified(self, team):
        s, token, h = self.connect(team)
        self.game_says(team, s["connect_code"], "th-" + team)
        self.assertTrue(self.call("GET", "/plaza/api/connect/status?session=" + s["session"])[1]["verified"])
        return s["session"], {"X-Plaza-Token": token}

    def everything_public(self, extra=()):
        admin = {"X-Plaza-Admin": "test-admin-token"}
        blob = ""
        for path in ("/plaza/api/teams", "/plaza/api/team/t07", "/plaza/api/team/t09", "/plaza/api/matches",
                     "/plaza/api/matches?team=t09", "/plaza/api/wall", "/plaza/api/offers?team=t09", "/plaza/api/floor",
                     "/plaza/api/card/LAT-06", "/plaza/api/health", "/plaza/agents.md", "/plaza/api/status", *extra):
            blob += json.dumps(self.call("GET", path)[1])
        for path in ("/plaza/admin/api/overview", "/plaza/admin/api/activity", "/plaza/admin/api/activity?team=t09",
                     "/plaza/admin/api/activity?team=t07", "/plaza/admin/api/matchmaker"):
            st, body, _ = self.call("GET", path, headers=admin)
            self.assertEqual(st, 200, path)
            blob += json.dumps(body)
        return blob

    def test_limits_are_private_to_the_team_and_matched_blindly(self):
        s7, tok7 = self.verified("t07")
        s9, tok9 = self.verified("t09")
        st, out, _ = self.call("PUT", "/plaza/api/team/t09", {"for_sale": [{"ref": "LAT-06", "price": 1777, "min": 1333, "value": 1991}]}, tok9)
        self.assertEqual((st, out["limits_saved"]), (200, 1))
        self.assertFalse(leaks(json.dumps(out["declared"]), "1333"))
        st, out, _ = self.call("POST", "/plaza/api/me/card/LAT-06?session=" + s7, {"max": 1771})   # the human, from the page
        self.assertEqual((st, out["limits"]), (200, {"max": 1771}))
        self.assertEqual(self.call("GET", "/plaza/api/agent/cards", headers=tok9)[1]["limits"], {"LAT-06": {"min": 1333, "value": 1991}})
        self.assertEqual(self.call("GET", "/plaza/api/agent/cards", headers=tok7)[1]["limits"], {"LAT-06": {"max": 1771}})
        self.assertEqual(self.call("GET", "/plaza/api/me?session=" + s7)[1]["limits"], {"LAT-06": {"max": 1771}})
        self.assertIsNone(self.call("GET", "/plaza/api/team/t07")[1]["trades"][0]["price"])   # not for everybody
        st, home, _ = self.call("GET", "/plaza/api/team/t07", headers=tok7)
        price = home["trades"][0]["price"]                                 # inside the overlap, and not its middle:
        self.assertTrue(1333 <= price <= 1771 and price != 1552, price)    # a team cannot work the other limit out
        mid = home["trades"][0]["id"]
        self.assertNotIn("basis", home["trades"][0])
        queues = json.dumps(self.call("GET", "/plaza/api/agent/next", headers=tok7)[1])
        self.assertFalse(leaks(queues, "1333"))                            # the other side's limit is not in my queue
        self.assertFalse(leaks(queues, "1991"))
        other = json.dumps(self.call("GET", "/plaza/api/agent/next", headers=tok9)[1])
        self.assertFalse(leaks(other, "1771"))
        errors = ""
        for body in ({"action": "counter", "price": 1}, {"action": "nope"}, {"action": "counter", "price": 99999}):
            errors += json.dumps(self.call("POST", f"/plaza/api/match/{mid}/message", body, tok7)[1])
        errors += json.dumps(self.call("POST", "/plaza/api/me/card/LAT-06?session=" + s7, {"max": "x"})[1])
        errors += json.dumps(self.call("GET", "/plaza/api/agent/cards")[1])
        blob = self.everything_public((f"/plaza/api/match/{mid}",)) + errors
        for secret in ("1333", "1991", "1771"):
            self.assertFalse(leaks(blob, secret), secret)
        st, mm, _ = self.call("GET", "/plaza/admin/api/matchmaker", headers={"X-Plaza-Admin": "test-admin-token"})
        self.assertEqual((mm["queue"][0]["overlap"], mm["queue"][0]["basis"]), (True, "limits"))     # yes or no; no numbers
        st, ov, _ = self.call("GET", "/plaza/admin/api/overview", headers={"X-Plaza-Admin": "test-admin-token"})
        self.assertEqual({t["team"]: t["limits_set"] for t in ov["teams"] if t["team"] in ("t07", "t08", "t09")},
                         {"t07": True, "t08": False, "t09": True})
        act = self.call("GET", "/plaza/admin/api/activity?team=t09", headers={"X-Plaza-Admin": "test-admin-token"})[1]
        self.assertEqual(act["limits_set"], ["LAT-06"])
        # no overlap: the match is withdrawn, and nobody is told why
        self.assertEqual(self.call("POST", "/plaza/api/me/card/LAT-06?session=" + s7, {"max": 1001})[0], 200)
        self.board.quoter.kept.clear()                                     # once the answer given has run its hold
        self.board.stale()
        self.assertEqual(self.call("GET", "/plaza/api/team/t07")[1]["trades"], [])
        # nothing of it in the files our bot, brain and broker can read, nor in what the broker's matchmaker gets
        for path in self.live.rglob("*"):
            if path.is_file():
                raw = path.read_bytes()
                for secret in ("1333", "1991", "1771", "1001"):
                    self.assertFalse(leaks(raw, secret), (path.name, secret))
        self.assertEqual(sorted(p.name for p in (self.live.parent / "plaza_private").iterdir()),
                         ["key", "limits.bin", "limits.bin.bak"])           # the copy is sealed with the same key
        pairs = json.dumps(S.declared_pairs(self.live, self.record))
        for secret in ("1333", "1991", "1001", "1552"):
            self.assertFalse(leaks(pairs, secret), secret)

    def test_other_teams_and_strangers_cannot_read_or_write_limits(self):
        s7, tok7 = self.verified("t07")
        _, tok8 = self.verified("t08")
        self.call("POST", "/plaza/api/me/card/LAT-06?session=" + s7, {"max": 1771, "value": 1991})
        self.assertEqual(self.call("GET", "/plaza/api/agent/cards", headers=tok8)[1]["limits"], {})
        self.assertEqual(self.call("GET", "/plaza/api/agent/cards")[0], 401)
        self.assertEqual(self.call("GET", "/plaza/api/agent/next")[0], 401)
        self.assertEqual(self.call("GET", "/plaza/api/agent/cards", headers={"X-Plaza-Admin": "test-admin-token"})[0], 401)
        self.assertEqual(self.call("POST", "/plaza/api/me/card/LAT-06", {"max": 5})[0], 401)                # no session
        self.assertEqual(self.call("POST", "/plaza/api/me/card/LAT-06?session=" + "x" * 32, {"max": 5})[0], 401)
        self.assertEqual(self.call("POST", "/plaza/api/me/card/ZZZ-99?session=" + s7, {"max": 5})[0], 404)
        self.assertEqual(self.call("POST", "/plaza/api/me/card/LAT-06?session=" + s7, {"price": 5})[0], 400)
        fresh = self.call("POST", "/plaza/api/connect/start", {"team": "t09"})[1]["session"]              # not proven
        self.assertEqual(self.call("POST", "/plaza/api/me/card/LAT-06?session=" + fresh, {"min": 5})[0], 403)
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 5}]}, tok8)[0], 403)
        self.assertEqual(self.call("GET", "/plaza/api/me?session=" + s7)[1]["limits"], {"LAT-06": {"max": 1771, "value": 1991}})

    def test_queue_and_human_orders_through_http(self):
        s7, tok7 = self.verified("t07")
        s9, tok9 = self.verified("t09")
        self.board.vault.put("t07", "LAT-06", {"max": 25})                          # its own limit: auto may go ahead
        st, nxt, _ = self.call("GET", "/plaza/api/agent/next", headers=tok7)
        self.assertEqual([a["type"] for a in nxt["actions"]], ["sync_cards", "post_offer"])
        mid = nxt["actions"][1]["match"]
        self.assertEqual(nxt["actions"][1]["request"]["body"]["to"], "t09")
        st, ack, _ = self.call("POST", "/plaza/api/agent/ack", {"id": nxt["actions"][0]["id"], "status": "done"}, tok7)
        self.assertEqual((st, ack["status"]), (200, "done"))
        again = self.call("GET", "/plaza/api/agent/next", headers=tok7)[1]      # no sheet yet: asked again whatever was acked
        self.assertEqual((again["actions"][0]["type"], "NOT DONE" in again["next"]), ("sync_cards", True))
        self.assertEqual(self.call("POST", "/plaza/api/agent/ack", {"id": "a-000000000000", "status": "done"})[0], 401)
        self.assertEqual(self.call("POST", "/plaza/api/agent/ack", {"id": 5, "status": "done"}, tok7)[0], 400)
        url = f"/plaza/api/me/trade/{mid}?session=" + s7
        self.assertEqual(self.call("POST", url, {"mode": "ask_me"})[1]["agent"]["modes"], {mid: "ask_me"})
        self.assertEqual([a["type"] for a in self.call("GET", "/plaza/api/agent/next", headers=tok7)[1]["actions"] if a["type"] != "sync_cards"], [])
        self.assertEqual(self.call("POST", url, {"order": "counter", "price": 2})[1]["error"], "below_floor")
        self.assertEqual(self.call("POST", url, {"order": "counter", "price": 15})[0], 200)
        act = self.call("GET", "/plaza/api/agent/next", headers=tok7)[1]["actions"]
        self.assertEqual([(a["type"], a["request"]["body"]) for a in act if a["type"] != "sync_cards"], [("counter", {"action": "counter", "price": 15})])
        _, s8tok = self.verified("t08")
        s8 = self.call("POST", "/plaza/api/connect/start", {"team": "t08"})[1]["session"]
        self.assertIn(self.call("POST", f"/plaza/api/me/trade/{mid}?session=" + s8, {"order": "pass"})[0], (403,))
        self.assertEqual(self.call("POST", f"/plaza/api/me/trade/{mid}", {"order": "pass"})[0], 401)
        self.assertEqual(self.call("POST", url, {"nope": 1})[0], 400)
        self.assertEqual(self.call("POST", "/plaza/api/me/settings?session=" + s9, {"default_mode": "ask_me"})[1]["agent"]["default_mode"], "ask_me")
        self.assertEqual([a["type"] for a in self.call("GET", "/plaza/api/agent/next", headers=tok9)[1]["actions"]], ["sync_cards"])
        self.assertEqual(self.call("GET", "/plaza/api/me?session=" + s7)[1]["agent"]["orders"][mid]["action"], "counter")


class HostingTest(unittest.TestCase):
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call

    def test_lives_behind_its_own_hostname(self):
        import urllib.request

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            urllib.request.build_opener(NoRedirect).open(self.base + "/", timeout=5)
            self.fail("the root redirects")
        except urllib.error.HTTPError as e:
            self.assertEqual((e.code, e.headers["Location"]), (302, "/plaza/"))
            e.close()
        self.assertEqual(self.call("GET", "/plaza/api/teams", headers={"Host": "plaza.example.org"})[0], 200)
        admin = {"X-Plaza-Admin": "test-admin-token"}
        self.assertEqual(self.call("GET", "/plaza/admin/api/overview", headers=admin)[0], 200)
        for cf in ({"CF-Connecting-IP": "203.0.113.9"}, {"CF-Ray": "abc"}):         # never through the public hostname
            self.assertEqual(self.call("GET", "/plaza/admin/api/overview", headers={**admin, **cf})[0], 404)
            self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "off"}, {**admin, **cf})[0], 404)
        st, s, h = self.call("POST", "/plaza/api/connect/start", {"team": "t07"}, {"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", h["Set-Cookie"])

    def test_public_url_and_name_come_from_settings(self):
        old = {k: os.environ.get(k) for k in ("PLAZA_PUBLIC_URL",)}
        try:
            os.environ["PLAZA_PUBLIC_URL"] = "https://market.example.org"
            self.assertEqual(S.public_url(self.live), "https://market.example.org/plaza")
            st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": "t07"})
            self.assertIn("PLAZA=https://market.example.org/plaza PLAZA_CODE=", s["prompt"])
            self.assertLessEqual(len(s["prompt"]), 900)
            os.environ["PLAZA_PUBLIC_URL"] = "javascript:alert(1)"
            self.assertIsNone(S.public_url(self.live))
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIn("# Mercadillo:", S.agents_md(name="Mercadillo"))
        st, texts, _ = self.call("GET", "/plaza/i18n.json")
        self.assertEqual((st, texts["languages"], set(texts["en"]) == set(texts["es"])), (200, ["en", "es"], True))
        self.assertIn("only your team sees your limits", texts["en"]["private.note"])
        self.assertEqual(self.call("GET", "/plaza/api/health")[1]["name"], S.NAME)

    def test_per_client_budget_uses_the_address_cloudflare_reports(self):
        codes = [self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "x"}, {"CF-Connecting-IP": "203.0.113.9",
                                                                                  "X-Plaza-Client": f"198.51.100.{i}"})[0]
                 for i in range(S.WRITES_PER_MIN * S.SHARED_READS + 2)]     # one address is a whole room
        self.assertEqual((codes[0], codes[-1]), (400, 429))    # a made-up X-Plaza-Client does not dodge the budget


class FirewallTest(unittest.TestCase):
    def test_nothing_outside_the_plaza_touches_the_private_data(self):
        """Our bot, brain, broker and dashboard never import the vault nor name its folder."""
        rx = re.compile(r"plaza_private|plaza\.private|plaza import private|limits\.bin|Vault\(")
        hits = []
        for folder in ("bazaar", "legacy"):
            for path in (REPO / folder).rglob("*.py"):
                rel = path.relative_to(REPO).as_posix()
                if rel.startswith("bazaar/plaza/") or "/data/" in rel:
                    continue
                if rx.search(path.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(rel)
        self.assertEqual(hits, [])

    def test_the_vault_is_not_under_the_live_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "live").mkdir()
            (root / "record" / "latest").mkdir(parents=True)
            board = S.Board(root / "live", root / "record", report_fn=lambda: {})
            self.assertNotIn(root / "live", board.vault.folder.parents)
            self.assertNotEqual(board.vault.folder, root / "live")


if __name__ == "__main__":
    unittest.main()
