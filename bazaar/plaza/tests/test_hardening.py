"""What the security review found in the server, the connection flow and the store, each as a test that failed
before its fix: a token is nobody until its team proved itself, nobody keeps a team from connecting, a request never
leaves bytes for the next one, a limit counts the team and not a made-up token, the panel never answers a public
hostname, the venue makes no trade up, and a slow board is built by one thread while the others read the last one."""
import json
import socket
import threading
import time
import unittest

from bazaar.plaza import connect as C, server as S
from bazaar.plaza.tests import test_server as T

ADMIN = {"X-Plaza-Admin": "test-admin-token"}


class Base(unittest.TestCase):
    setUp, tearDown, call, pin = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call, T.ServerTest.pin

    def raw(self, data: bytes, wait: float = 1.5) -> bytes:
        """Everything the server answers on one connection until it closes it (or `wait` passes)."""
        with socket.create_connection(self.srv.server_address, timeout=5) as s:
            s.sendall(data)
            s.settimeout(wait)
            out = b""
            try:
                while chunk := s.recv(65536):
                    out += chunk
            except OSError:
                pass
            return out

    def agent(self, team, prove=True, client=None):
        h = {"X-Plaza-Client": client} if client else {}
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": team}, h)
        self.assertEqual(st, 200, s)
        st, a, _ = self.call("POST", "/plaza/api/connect/agent", {"team": team, "code": s["connect_code"]}, h)
        self.assertEqual(st, 200, a)
        if prove:
            self.game_says(team, s["connect_code"])
        return s, {"X-Plaza-Token": a["agent_token"]}

    def game_says(self, team, text, name=None):
        (self.record / "threads" / f"{name or 'th-' + team}.json").write_text(json.dumps(
            {"id": team, "kind": "team", "messages": [{"sender": team, "text": text}]}) + "\n")
        self.board.verified_at = 0.0


class IdentityTest(Base):
    def test_an_unproved_token_reads_and_writes_nothing_of_the_team(self):
        real_s, real = self.agent("t07")                                     # the real team, proved, with a limit
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 1777}]}, real)[0], 200)
        thief_s, thief = self.agent("t07", prove=False)                      # anybody: a code and a token for t07
        for method, path, body in (("GET", "/plaza/api/me/cards", None), ("GET", "/plaza/api/agent/cards", None),
                                   ("GET", "/plaza/api/me/trades", None), ("GET", "/plaza/api/me/activity", None),
                                   ("PUT", "/plaza/api/team/t07", {"wants": []}),
                                   ("POST", "/plaza/api/me/card/LAT-06", {"max": 5}),
                                   ("POST", "/plaza/api/floor", {"kind": "note", "text": "hi"}),
                                   ("POST", "/plaza/api/suggestions", {"text": "x"})):
            st, out, _ = self.call(method, path, body, thief)
            self.assertEqual((st, out.get("error")), (403, "prove_first"), path)
            self.assertNotIn("1777", json.dumps(out))
        for path in ("/plaza/api/me", "/plaza/api/agent/next", "/plaza/api/status"):
            st, out, _ = self.call("GET", path, headers=thief)
            self.assertNotIn("1777", json.dumps(out), path)
            self.assertNotIn("LAT-06", json.dumps(out.get("limits", {})), path)
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=real)[1]["want"][0]["limits"], {"max": 1777})

    def test_a_proof_seen_before_the_agent_calls_puts_the_earlier_agent_out(self):
        _, planted = self.agent("t08", prove=False)                          # somebody redeemed a code for t08 first
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": "t08"})
        self.game_says("t08", s["connect_code"])                             # the team proves ITS code...
        self.assertTrue(self.call("GET", "/plaza/api/connect/status?session=" + s["session"])[1]["verified"])
        self.assertEqual(self.call("GET", "/plaza/api/agent/next", headers=planted)[0], 401)   # ...the planted one is out
        st, a, _ = self.call("POST", "/plaza/api/connect/agent", {"team": "t08", "code": s["connect_code"]})
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers={"X-Plaza-Token": a["agent_token"]})[0], 200)

    def test_twenty_teams_connect_from_one_address_in_a_minute(self):
        """The whole room shares one public address: nobody's connection spends another team's share."""
        room = "83.40.1.7"
        teams = [t for t in S.public.TEAMS if t != S.HOST]
        for team in teams:
            s, tok = self.agent(team, client=room)
            st, out, _ = self.call("PUT", f"/plaza/api/team/{team}", {"wants": ["LAT-06"]}, {**tok, "X-Plaza-Client": room})
            self.assertEqual(st, 200, (team, out))
            for path in ("/plaza/api/agent/next", "/plaza/api/me", "/plaza/api/status", "/plaza/api/teams"):
                self.assertEqual(self.call("GET", path, headers={**tok, "X-Plaza-Client": room})[0], 200, (team, path))
        self.assertGreaterEqual(len(teams), 17)

    def test_nobody_keeps_a_team_from_connecting(self):
        st, real, _ = self.call("POST", "/plaza/api/connect/start", {"team": "t09"}, {"X-Plaza-Client": "83.40.1.7"})
        for i in range(30):                                                  # starts for t09 from elsewhere
            self.call("POST", "/plaza/api/connect/start", {"team": "t09"}, {"X-Plaza-Client": f"6.6.6.{i}"})
        for i in range(30):                                                  # and wrong codes for t09
            self.call("POST", "/plaza/api/connect/agent", {"team": "t09", "code": "PLAZA-222222"}, {"X-Plaza-Client": "6.6.6.6"})
        st, a, _ = self.call("POST", "/plaza/api/connect/agent", {"team": "t09", "code": real["connect_code"]},
                             {"X-Plaza-Client": "83.40.1.7"})
        self.assertEqual(st, 200, a)

    def test_a_proof_in_an_old_thread_is_still_found(self):
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": "t07"})
        self.game_says("t07", s["connect_code"], "proof")
        for i in range(90):                                                  # ninety newer threads after it
            (self.record / "threads" / f"n{i}.json").write_text(json.dumps({"id": i, "kind": "team", "messages": []}) + "\n")
        self.board.verified_at = 0.0
        self.assertTrue(self.call("GET", "/plaza/api/connect/status?session=" + s["session"])[1]["verified"])

    def test_a_session_in_an_address_opens_nothing(self):
        s, _ = self.agent("t07")
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers={"Cookie": "plaza_session=" + s["session"]})[0], 200)
        with_url = T.urllib.request.Request(self.base + "/plaza/api/me/cards?session=" + s["session"])
        with self.assertRaises(T.urllib.error.HTTPError) as e:
            T.urllib.request.urlopen(with_url, timeout=5)
        self.assertEqual(e.exception.code, 401)
        e.exception.close()


class WireTest(Base):
    GET = b"GET /plaza/api/health HTTP/1.1\r\nHost: x\r\n\r\n"

    def test_an_unread_body_is_never_taken_for_the_next_request(self):
        post = "POST /plaza/api/floor HTTP/1.1\r\nHost: x\r\nContent-Type: {ct}\r\nContent-Length: {n}\r\n\r\n"
        for head in (post.format(ct="text/plain", n=len(self.GET)),                       # 415 before the body
                     "GET /plaza/api/health HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n" % len(self.GET),
                     "OPTIONS /plaza/api/floor HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n" % len(self.GET),
                     "GET /plaza/api/health HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"):
            got = self.raw(head.encode() + self.GET)
            self.assertEqual(got.count(b"HTTP/1.1 "), 1, head)                # one answer, then the connection ends
            self.assertIn(b"Connection: close", got, head)
        got = self.raw(self.GET + self.GET)                                    # two honest requests still get two
        self.assertEqual(got.count(b"HTTP/1.1 200"), 2)

    def test_a_budget_refusal_closes_the_connection_too(self):
        self.srv.RequestHandlerClass.budget.take = lambda *a: False
        got = self.raw(b"POST /plaza/api/floor HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                       b"Content-Length: %d\r\n\r\n" % len(self.GET) + self.GET)
        self.assertEqual((got.count(b"HTTP/1.1 "), got[:12]), (1, b"HTTP/1.1 429"))

    def test_a_bad_length_is_refused_and_nobody_parks_a_thread(self):
        t0 = time.monotonic()
        for length in (b"-1", b"abc", b"1e3", b"99999999999999999999"):
            got = self.raw(b"POST /plaza/api/floor HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                           b"Content-Length: " + length + b"\r\n\r\n{}")
            self.assertRegex(got[:12], rb"HTTP/1\.1 4(00|13)", length)
        self.assertLess(time.monotonic() - t0, 4.0)
        self.assertLessEqual(S.Handler.timeout, 20.0)                          # a silent peer is dropped
        self.assertEqual(self.call("GET", "/plaza/api/health")[0], 200)

    def test_only_json_and_only_from_our_own_page(self):
        s, _ = self.agent("t07")
        cookie = {"Cookie": "plaza_session=" + s["session"]}
        body = {"lang": "es"}
        for ctype in ("text/plain;json", "text/plain; charset=json", "application/x-www-form-urlencoded", "json"):
            self.assertEqual(self.call("POST", "/plaza/api/me/settings", body, {**cookie, "Content-Type": ctype})[0], 415, ctype)
        for extra in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
            st, out, _ = self.call("POST", "/plaza/api/me/settings", body, {**cookie, **extra})
            self.assertEqual((st, out["error"]), (403, "cross_site"), extra)
        host = self.base.split("//")[1]
        for extra in ({}, {"Origin": "http://" + host, "Sec-Fetch-Site": "same-origin"},
                      {"Origin": "https://m.example.org", "X-Plaza-Host": "m.example.org"},
                      {"Content-Type": "application/json; charset=utf-8"}):
            self.assertEqual(self.call("POST", "/plaza/api/me/settings", body, {**cookie, **extra})[0], 200, extra)

    def test_whatever_breaks_inside_answers_json_without_a_trace(self):
        def boom(*a, **k):
            raise RuntimeError("secret detail /Users/somebody")
        self.board.teams_view = boom
        st, out, _ = self.call("GET", "/plaza/api/teams")
        self.assertEqual((st, out["error"]), (500, "server_error"))
        self.assertNotIn("secret", json.dumps(out))
        self.board.store.claim = boom
        st, out, _ = self.call("POST", "/plaza/api/claim", {"team": "t07", "pin": "42424242"})
        self.assertEqual((st, set(out)), (500, {"error", "message"}))
        deep = b"[" * 7000 + b"]" * 7000
        got = self.raw(b"POST /plaza/api/floor HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: %d"
                       b"\r\nConnection: close\r\n\r\n" % len(deep) + deep)
        self.assertRegex(got[:12], rb"HTTP/1\.1 400")
        self.assertEqual(self.call("GET", "/plaza/api/health")[0], 200)


class LimitsTest(Base):
    def test_a_made_up_token_does_not_buy_a_budget(self):
        keys = set()
        handler = self.srv.RequestHandlerClass
        take = handler.budget.take
        handler.budget.take = lambda key, kind: keys.add(key) or take(key, kind)
        for i in range(6):
            self.call("GET", "/plaza/api/teams", headers={"X-Plaza-Token": f"made-up-token-number-{i:04d}-xxxxxxxx"})
            self.call("GET", "/plaza/api/teams", headers={"Cookie": f"plaza_session=made-up-session-number-{i:04d}"})
        self.assertEqual(keys, {"127.0.0.1"})                                  # all of them: the address
        s, tok = self.agent("t07", prove=False)
        cookie = {"Cookie": "plaza_session=" + s["session"]}
        keys.clear()
        self.call("GET", "/plaza/api/teams", headers=tok)                      # started, never proved: anybody can do
        self.call("GET", "/plaza/api/teams", headers=cookie)                   # that in a team's name, so it counts
        self.assertEqual(keys, {"127.0.0.1"})                                  # against the address, not the team
        self.game_says("t07", s["connect_code"])
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=tok)[0], 200)
        keys.clear()
        self.call("GET", "/plaza/api/teams", headers=tok)
        self.call("GET", "/plaza/api/teams", headers=cookie)
        self.assertEqual(keys, {"k:t07"})                                      # proved: its team

    def test_nobody_spends_a_teams_budget_or_its_streams(self):
        _, real = self.agent("t09")
        self.assertEqual(self.call("GET", "/plaza/api/agent/next", headers=real)[0], 200)
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": "t09"}, {"X-Plaza-Client": "6.6.6.6"})
        thief = {"Cookie": "plaza_session=" + s["session"], "X-Plaza-Client": "6.6.6.6"}
        budget = self.srv.RequestHandlerClass.budget
        from unittest import mock
        with mock.patch.object(S, "READS_PER_MIN", 30):
            codes = {self.call("GET", "/plaza/api/teams", headers=thief)[0] for _ in range(60)}
            self.assertEqual(self.call("GET", "/plaza/api/agent/next", headers=real)[0], 200)   # t09 is untouched
        self.assertNotIn("k:t09", {k for k, kind in budget.hits if k == "k:t09" and len(budget.hits[(k, kind)]) > 5})
        del codes

    def test_connecting_is_not_locked_by_the_shared_budget(self):
        self.srv.RequestHandlerClass.budget.take = lambda *a: False            # the room spent every shared request
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": "t07"})
        self.assertEqual(st, 200)
        self.assertEqual(self.call("POST", "/plaza/api/connect/agent", {"team": "t07", "code": s["connect_code"]})[0], 200)

    def test_two_lengths_are_one_refusal(self):
        got = Base.raw(self, b"POST /plaza/api/floor HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                             b"Content-Length: 2\r\nContent-Length: 44\r\n\r\n{}GET /plaza/api/health HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertEqual((got.count(b"HTTP/1.1 "), got[:12]), (1, b"HTTP/1.1 400"))

    def test_an_old_pin_claim_is_no_longer_looked_for(self):
        self.board.store.claim("t05", "42424242")
        self.assertIn("t05", self.board.store.pending_codes())
        real = self.board.store.clock
        self.board.store.clock = lambda: real() + 31 * 60
        self.assertEqual(self.board.store.pending_codes(), {})

    def test_we_can_reset_a_team(self):
        s, tok = self.agent("t07")
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 1777}]}, tok)[0], 200)
        st, out, _ = self.call("POST", "/plaza/admin/api/action", {"action": "reset_team", "team": "t07"}, ADMIN)
        self.assertEqual((st, out["reset"]["agent"]), (200, True))
        self.assertEqual(self.call("GET", "/plaza/api/agent/next", headers=tok)[0], 401)
        self.assertEqual((self.board.vault.get("t07"), self.board.store.declared()["t07"]["verified"]), ({}, False))
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "reset_team", "team": "t10"}, ADMIN)[0], 400)
        self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "reset_team", "team": "t07"})[0], 404)
        _, again = self.agent("t07")                                           # and it connects again from nothing
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=again)[1]["want"], [])

    def test_a_forwarded_address_is_believed_from_this_machine_only(self):
        h = S.Handler.__new__(S.Handler)
        h.headers = {"CF-Connecting-IP": "203.0.113.9"}
        h.client_address = ("127.0.0.1", 1)
        self.assertEqual(h._client(), "203.0.113.9")
        h.headers = {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}              # ngrok's
        self.assertEqual(h._client(), "198.51.100.7")
        h.client_address = ("192.168.1.50", 1)                                 # somebody on the network writes it
        self.assertEqual(h._client(), "192.168.1.50")

    def test_a_room_behind_one_address_gets_its_live_floor(self):
        board, n = self.board, 0
        with board.lock:
            board.streams.clear()
        room = "83.40.1.7"
        self.assertGreaterEqual(S.STREAMS_PER_ADDRESS, 60)                     # twenty teams, three tabs each
        self.assertGreaterEqual(S.STREAMS_MAX - S.STREAMS_ANON, 17 * S.STREAMS_PER_CLIENT)   # connected teams never
        del room, n                                                            # wait behind anonymous watchers


class RoomTest(Base):
    """Limits stop abuse, never use: the whole venue behind one address never sees a 429."""
    ROOM = "83.40.1.7"

    def test_twenty_teams_use_the_market_for_ten_minutes_from_one_address_without_a_429(self):
        import http.client
        now = [1000.0]
        handler = self.srv.RequestHandlerClass
        handler.budget.clock = lambda: now[0]                                  # ten minutes pass in the counters
        teams = [t for t in S.public.TEAMS if t != S.HOST]
        refused, conn = [], http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)

        def ask(method, path, headers, body=None):
            data = json.dumps(body).encode() if body is not None else None
            h = {"X-Plaza-Client": self.ROOM, **headers, **({"Content-Type": "application/json"} if data else {})}
            conn.request(method, path, body=data, headers=h)
            r = conn.getresponse()
            raw = r.read()
            if r.status == 429 or r.status >= 500:
                refused.append((method, path, r.status, raw[:120]))
            return r.status

        cred = {}
        for team in teams:                                                     # the first minutes: everybody connects,
            for _ in range(3):                                                 # and tries a few times
                ask("POST", "/plaza/api/connect/start", {}, {"team": team})
            ask("POST", "/plaza/api/connect/agent", {}, {"team": team, "code": "PLAZA-222222"})    # a typo
            s, tok = self.agent(team, client=self.ROOM)
            cred[team] = (tok, {"Cookie": "plaza_session=" + s["session"]})
        self.board.team_limiter.clock = lambda: now[0]
        streams = []
        for team in teams:                                                     # three open pages a team, each with
            for _ in range(3):                                                 # its live floor
                sock = socket.create_connection(self.srv.server_address, timeout=5)
                sock.sendall(f"GET /plaza/api/floor/stream HTTP/1.1\r\nHost: x\r\nX-Plaza-Client: {self.ROOM}\r\n"
                             f"Cookie: {cred[team][1]['Cookie']}\r\n\r\n".encode())
                streams.append((team, sock, sock.recv(64)))
        self.assertEqual([x[2][:12] for x in streams if x[2][:12] != b"HTTP/1.1 200"], [])
        pages = ("/plaza/api/me", "/plaza/api/me/trades", "/plaza/api/floor?since=0", "/plaza/api/market",
                 "/plaza/api/me/cards", "/plaza/api/me/activity")
        for step in range(120):                                                # 600 s, every 5 s
            now[0] += 5.0
            for team in teams:
                tok, cookie = cred[team]
                ask("GET", "/plaza/api/agent/next", tok)                       # the agent: its queue and its trades
                ask("GET", "/plaza/api/me/trades", tok)
                if step % 12 == 0:                                             # and its sheet once a minute
                    ask("PUT", f"/plaza/api/team/{team}", tok, {"wants": ["LAT-06"], "have": ["LAT-03"]})
                for tab in range(3):                                           # three pages: the bar and one panel each
                    ask("GET", "/plaza/api/status", cookie)
                    ask("GET", pages[(step + tab) % len(pages)], cookie)
            if step % 12 == 0:                                                 # and somebody without a session looks too
                for path in ("/plaza/api/teams", "/plaza/api/market", "/plaza/api/status"):
                    ask("GET", path, {})
        for _, sock, _ in streams:
            sock.close()
        conn.close()
        self.assertEqual(refused, [])                                          # not one 429, not one 5xx

    def test_a_429_says_how_long_and_it_is_short(self):
        _, tok = self.agent("t07")
        self.srv.RequestHandlerClass.budget.take = lambda *a: False
        st, out, h = self.call("GET", "/plaza/api/teams", headers=tok)
        self.assertEqual((st, out["error"], out["retry_after_s"], h["Retry-After"]), (429, "slow_down", S.RETRY_S, str(S.RETRY_S)))
        self.assertLessEqual(S.RETRY_S, 10)
        self.assertIn("seconds", out["message"])


class PanelTest(Base):
    def test_the_panel_never_answers_a_public_hostname(self):
        self.assertEqual(self.call("GET", "/plaza/admin/api/overview", headers=ADMIN)[0], 200)
        for extra in ({"CF-Connecting-IP": "203.0.113.9"}, {"CF-Ray": "abc"}, {"X-Plaza-Public": "1"},
                      {"X-Forwarded-For": "203.0.113.9"}):
            self.assertEqual(self.call("GET", "/plaza/admin/api/overview", headers={**ADMIN, **extra})[0], 404, extra)
            self.assertEqual(self.call("GET", "/plaza/admin/", headers={**ADMIN, **extra})[0], 404, extra)
            self.assertEqual(self.call("POST", "/plaza/admin/api/action", {"action": "off"}, {**ADMIN, **extra})[0], 404, extra)
        self.assertTrue(self.call("GET", "/plaza/api/health")[1]["enabled"])
        self.assertEqual(self.call("GET", "/plaza/_kit")[0], 200)              # the page of components: here only
        for extra in ({"CF-Ray": "abc"}, {"X-Plaza-Public": "1"}, {"X-Plaza-Host": "dashboard.example.org"}):
            self.assertEqual(self.call("GET", "/plaza/_kit", headers=extra)[0], 404, extra)
            self.assertEqual(self.call("GET", "/plaza/", headers=extra)[0], 200, extra)

    def test_the_panel_learns_overlap_only_when_both_limits_are_set(self):
        self.board.vault.put("t09", "LAT-06", {"min": 83})                     # one side only
        self.board.stale()
        mm = self.call("GET", "/plaza/admin/api/matchmaker", headers=ADMIN)[1]
        rows = [r for r in mm["queue"] if r["kind"] == "sale" and r["ref"] == "LAT-06"]
        self.assertTrue(rows)
        self.assertEqual({r["overlap"] for r in rows}, {None})                 # nothing to learn from one limit
        self.assertNotIn("83", json.dumps(mm))

    def test_the_venue_makes_no_trade_up_and_picks_no_price(self):
        self.board.vault.put("t09", "LAT-06", {"min": 83})
        act = lambda **b: self.call("POST", "/plaza/admin/api/action", {"action": "force", **b}, ADMIN)   # noqa: E731
        st, out, _ = act(seller="t02", buyer="t03", ref="LAT-03")
        self.assertEqual((st, out["error"]), (400, "not_listed"))
        answers = set()
        for price in (15, 40, 60, 80, 83, 84, 100, 200, 1000):                 # walking a forced price finds no limit
            st, out, _ = act(seller="t09", buyer="t07", ref="LAT-06", price=price)
            answers.add((st, out.get("error")))
            if st == 200:
                self.call("POST", "/plaza/admin/api/action", {"action": "expire", "match": out["match"]}, ADMIN)
        self.assertLessEqual(answers, {(200, None), (400, "off_reference"), (400, "below_floor")})
        self.assertIn((400, "off_reference"), answers)


class BoardTest(Base):
    def test_a_stale_board_is_built_once_while_others_read_the_last_one(self):
        board, built = self.board, []
        real = board._rebuild

        def slow():
            built.append(1)
            time.sleep(0.6)
            return real()
        board._rebuild = slow
        board.get()
        built.clear()
        board.stale()
        got, t0 = [], time.monotonic()
        threads = [threading.Thread(target=lambda: got.append(board.get())) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((len(got), len(built)), (12, 1))                      # twelve readers, one build
        self.assertLess(time.monotonic() - t0, 2.5)

    def test_a_slow_board_is_not_rebuilt_at_every_write(self):
        board, built = self.board, []
        real = board._rebuild
        board._rebuild = lambda: built.append(1) or real()
        board.rebuild()
        board.built_in, board.wait_until = 3.0, time.monotonic() + 15.0       # the last build was slow
        for _ in range(20):
            board.stale()
            self.assertIn("sheets", board.get())                               # the last good board, at once
        self.assertEqual(len(built), 1)
        board.wait_until = 0.0
        board.get()
        self.assertEqual(len(built), 2)

    def test_the_feed_file_is_read_from_where_it_was_left(self):
        board = self.board
        first = board._stats()
        self.assertEqual((first["deals"], first["volume"]), (1, 20))
        size = (self.live / "events.jsonl").stat().st_size
        self.assertEqual(board.stats_at[1], size)
        with (self.live / "events.jsonl").open("a") as f:
            f.write(json.dumps({"tick": 9, "type": "settlement", "payload": {"venue": "v07", "price": 30}}) + "\n")
            f.write('{"tick": 10, "type": "settlement", "payload": {"venue": "v07", "price"')      # still being written
        again = board._stats()
        self.assertEqual((again["deals"], again["volume"], again["last_deal_tick"]), (2, 50, 9))
        (self.live / "events.jsonl").write_text("")                           # rotated: counted again from the start
        self.assertEqual(board._stats()["deals"], 0)

    def test_every_answer_gives_the_tick_of_now(self):
        (self.record / "latest" / "clock.json").write_text(json.dumps(
            {"tick": 1526, "tick_seconds": 15.0, "next_tick_in": 9.0, "paused": False, "doors": "open"}))
        _, tok = self.agent("t07")
        now = self.call("GET", "/plaza/api/status")[1]
        self.assertEqual((now["tick"], now["tick_seconds"]), (1526, 15.0))     # the game's own clock, never a constant
        for path in ("/plaza/api/agent/next", "/plaza/api/me/trades", "/plaza/api/me", "/plaza/api/me/cards"):
            self.assertEqual(self.call("GET", path, headers=tok)[1]["tick"], 1526, path)
        self.assertEqual(self.call("GET", "/plaza/api/teams")[1]["tick"], 1526)

    def test_hourly_counters_survive_a_broken_write(self):
        self.board.hour("requests")
        self.board.save_hours()
        self.board.hour("requests")
        self.board.save_hours()
        (self.live / "plaza_hourly.json").write_text("{broken")
        self.assertTrue(self.board._load_hours())                              # read from the copy


if __name__ == "__main__":
    unittest.main()
