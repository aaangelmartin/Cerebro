"""Hidden demand: a coarse word about a team's own cards, from which nobody's limit can be read."""
import json
import random
import unittest

from bazaar.plaza import signals as S
from bazaar.plaza.tests import test_deals_api as DA
from bazaar.plaza.tests import test_server as T


class LevelTest(unittest.TestCase):
    def test_one_team_alone_is_never_reported_and_looks_like_none(self):
        self.assertEqual(S.level([], 100, True), (None, 0))
        self.assertEqual(S.level([500], 100, True), (None, 0))
        self.assertEqual(S.level([500, 90], 100, True), (None, 0))
        self.assertEqual(S.level([115, 112], 100, True), ("some", 2))
        self.assertEqual(S.level([131, 140, 111, 112], 100, True), ("strong", 2))
        self.assertEqual(S.level([60, 65, 95], 100, False), ("strong", 2))          # supply: a min well under the ask
        self.assertEqual((S.bucket(2), S.bucket(3), S.bucket(4), S.bucket(17)), ("2-3", "2-3", "4+", "4+"))

    def test_the_answers_do_not_pin_a_limit(self):
        """Whatever marks an attacker could try, the answer only ever says which of three bands the SECOND
        highest max is in, relative to the mark: never a number, never the highest, never whose."""
        rng = random.Random(7)
        for _ in range(300):
            maxes = sorted(rng.randint(5, 400) for _ in range(rng.randint(2, 6)))
            second, base = maxes[-2], rng.randint(5, 400)
            lvl, n = S.level([float(m) for m in maxes], base, True)
            band = "strong" if second >= base * S.STRONG else "some" if second >= base * S.SOME else None
            self.assertEqual(lvl, band)
            self.assertIn(S.bucket(n) if lvl else None, ("2-3", "4+", None))
            top = maxes[-1]                                         # moving the highest never changes the answer
            self.assertEqual(S.level([float(m) for m in maxes[:-1]] + [top + 500.0], base, True)[0], lvl)


class HttpTest(unittest.TestCase):
    """t09 holds LAT-06 (the public sheet); t07, t05 and t03 want it with private maxes."""
    setUp, tearDown, call = T.ServerTest.setUp, T.ServerTest.tearDown, T.ServerTest.call
    connect = DA.RoutesTest.connect

    def want(self, team, token, mx):
        st, out, _ = self.call("PUT", f"/plaza/api/team/{team}", {"wants": [{"ref": "LAT-06", "max": mx}]}, token)
        self.assertEqual(st, 200, out)

    def signals(self, token):
        st, out, _ = self.call("GET", "/plaza/api/me/signals", headers=token)
        self.assertEqual(st, 200, out)
        return out

    def test_two_private_buyers_make_a_signal_one_does_not_and_it_holds(self):
        seller, a, b = self.connect("t09"), self.connect("t07"), self.connect("t05")
        self.assertEqual(self.call("GET", "/plaza/api/me/signals")[0], 401)
        self.want("t07", a, 1900)                                   # one team alone: nothing, like nobody
        self.board.rebuild()
        first = self.signals(seller)
        self.assertEqual(first["sell"], [])
        self.want("t05", b, 1800)
        self.board.rebuild()
        self.assertEqual(self.signals(seller)["sell"], [])          # the answer stands: the window is not over
        self.board.signals.held.clear()                             # ...60 ticks later
        out = self.signals(seller)
        (s,) = out["sell"]
        self.assertEqual((s["ref"], s["level"], s["teams"], s["action"]["body"]["list"]), ("LAT-06", "strong", "2-3", "spares"))
        text = json.dumps(out)
        for secret in ("1900", "1800", "t07", "t05"):
            self.assertNotIn(secret, text)                          # no price, no team
        acts = [x for x in self.call("GET", "/plaza/api/agent/next", headers=seller)[1]["actions"] if x["type"] == "signal"]
        self.assertEqual((len(acts), acts[0]["card"], len(acts[0]["id"])), (1, "LAT-06", 14))
        self.assertEqual(self.call("POST", "/plaza/api/agent/ack", {"id": acts[0]["id"], "status": "done"}, seller)[0], 200)
        self.assertFalse([x for x in self.call("GET", "/plaza/api/agent/next", headers=seller)[1]["actions"] if x["type"] == "signal"])
        self.assertEqual(self.signals(a)["sell"], [])               # the buyers learn nothing of each other from it
        for path, headers in (("/plaza/api/team/t09", None), ("/plaza/api/market", None), ("/plaza/board.json", None),
                              ("/plaza/api/card/LAT-06", b), ("/plaza/api/me", b), ("/plaza/admin/api/teams", {"X-Plaza-Admin": "test-admin-token"}),
                              ("/plaza/admin/api/status", {"X-Plaza-Admin": "test-admin-token"})):
            body = json.dumps(self.call("GET", path, headers=headers)[1])
            self.assertNotIn('"level"', body, path)
            self.assertNotIn("1900", body, path)
        files = "".join(p.read_text(errors="replace") for p in self.live.glob("*") if p.is_file())
        self.assertNotIn('"level": "strong"', files)                # nothing of it is written under data/live

    def test_moving_my_own_sheet_does_not_buy_a_new_answer_and_a_banned_team_is_out(self):
        seller, a, b = self.connect("t09"), self.connect("t07"), self.connect("t05")
        self.want("t07", a, 1900)
        self.want("t05", b, 1800)
        self.board.rebuild()
        before = self.signals(seller)
        self.assertEqual(len(before["sell"]), 1)
        self.call("PUT", "/plaza/api/team/t09", {"spares": ["LAT-06"], "have": ["LAT-06", "LAT-03"]}, seller)
        self.board.strikes.ban("t05", "abuse")                      # one buyer is gone: under the window nothing moves
        self.board.rebuild()
        after = self.signals(seller)
        self.assertEqual((after["sell"][0]["level"], after["next_refresh_tick"]), (before["sell"][0]["level"], before["next_refresh_tick"]))
        self.board.signals.held.clear()
        self.assertEqual(self.signals(seller)["sell"], [])          # a new window: one buyer alone says nothing
        self.assertEqual(self.call("GET", "/plaza/api/me/signals", headers=b)[0], 403)


if __name__ == "__main__":
    unittest.main()
