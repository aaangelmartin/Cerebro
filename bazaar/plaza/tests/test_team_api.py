"""The team's own routes: status, cards with overrides, private limits, settings, activity and suggestions.

Every answer keeps the shape of its fixture, a team reads and writes itself only, and rubbish gets a 4xx."""
import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from bazaar.plaza import activity as A
from bazaar.plaza import server as S
from bazaar.plaza import status as ST
from bazaar.plaza import suggest as SG
from bazaar.plaza import team_api as TA
from bazaar.plaza.store import PlazaError
from bazaar.plaza.tests import test_server as T
from bazaar.plaza.tests.test_private_queue import leaks

FIXTURES = Path(S.__file__).parent / "web" / "fixtures"
ADMIN = {"X-Plaza-Admin": "test-admin-token"}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def clock(record: Path, **over) -> None:
    data = {"tick": 1446, "tick_seconds": 15.0, "next_tick_in": 9.0, "paused": False, "doors": "open", "round": 3,
            "round_name": "Sunday", "next_opens": None, **over}
    (record / "latest" / "clock.json").write_text(json.dumps(data))


CATALOG = json.loads(json.dumps(T.CATALOG))
CATALOG["sets"][0]["cards"].append({"id": "LAT-05", "name": "Bocata de Calamares", "rarity": "common"})   # in no feed


class Base(unittest.TestCase):
    tearDown, call = T.ServerTest.tearDown, T.ServerTest.call

    def setUp(self):
        T.ServerTest.setUp(self)
        (self.record / "latest" / "catalog.json").write_text(json.dumps(CATALOG))
        self.board.stale()

    def verified(self, team):
        st, s, _ = self.call("POST", "/plaza/api/connect/start", {"team": team})
        self.assertEqual(st, 200, s)
        st, a, _ = self.call("POST", "/plaza/api/connect/agent", {"team": team, "code": s["connect_code"]})
        self.assertEqual(st, 200, a)
        (self.record / "threads" / f"th-{team}.json").write_text(json.dumps(
            {"id": team, "kind": "team", "messages": [{"sender": team, "text": s["connect_code"]}]}) + "\n")
        self.board.verified_at = 0.0
        self.assertTrue(self.call("GET", "/plaza/api/connect/status?session=" + s["session"])[1]["verified"])
        return "?session=" + s["session"], {"X-Plaza-Token": a["agent_token"]}


class StatusTest(Base):
    def test_shape_and_states(self):
        clock(self.record)
        st, out, h = self.call("GET", "/plaza/api/status")
        self.assertEqual(st, 200)
        self.assertEqual(set(out), set(fixture("status.json")))
        self.assertEqual((out["game"], out["market"], out["matchmaker"], out["feed"], out["agent"], out["team"]),
                         ("open", "open", "on", "ok", None, None))
        self.assertEqual((out["tick"], out["tick_seconds"], out["round"]), (1446, 15.0, 3))
        self.assertTrue(0 <= out["seconds_to_tick"] <= 15.0)
        self.assertEqual(out["venue"], {"id": "v07", "name": out["name"], "fee_bps": 0, "per_card": 0})
        self.assertEqual(h["Access-Control-Allow-Origin"], "*")
        clock(self.record, doors="closed", paused=True, next_opens="2026-10-04T09:00:00+02:00")
        out = self.call("GET", "/plaza/api/status")[1]
        self.assertEqual((out["game"], out["market"], out["matchmaker"], out["seconds_to_tick"], out["opens_tick"]),
                         ("closed", "closed", "waiting", None, 1447))
        self.assertEqual(out["opens"], "2026-10-04T09:00:00+02:00")
        self.assertIsInstance(out["opens_in_s"], int)
        self.assertEqual(set(out), set(fixture("status_closed.json")))
        clock(self.record, paused=True)
        out = self.call("GET", "/plaza/api/status")[1]
        self.assertEqual((out["game"], out["market"], out["matchmaker"], out["opens"]), ("paused", "paused", "waiting", None))
        self.call("POST", "/plaza/admin/api/action", {"action": "pause"}, ADMIN)
        clock(self.record)
        self.assertEqual(self.call("GET", "/plaza/api/status")[1]["matchmaker"], "paused")

    def test_agent_of_the_caller(self):
        clock(self.record)
        s7, tok7 = self.verified("t07")
        out = self.call("GET", "/plaza/api/status" + s7)[1]
        self.assertEqual((out["team"], out["agent"]), ("t07", "offline"))          # connected, never called since
        out = self.call("GET", "/plaza/api/status", headers=tok7)[1]
        self.assertEqual((out["team"], out["agent"]), ("t07", "connected"))
        self.assertEqual(self.call("GET", "/plaza/api/status" + s7)[1]["agent"], "connected")
        st, out, _ = self.call("GET", "/plaza/api/status", headers={"X-Plaza-Token": "x" * 32})   # a bad token: nobody
        self.assertEqual((st, out["team"], out["agent"]), (200, None, None))

    def test_the_clock_is_read_not_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d)
            (rec / "latest").mkdir()
            out = ST.status(rec, "v07", True, False)                               # no recorder file at all
            self.assertEqual((out["game"], out["feed"], out["tick"], out["seconds_to_tick"]), ("closed", "stale", None, None))
            (rec / "latest" / "clock.json").write_text("{not json")
            self.assertEqual(ST.status(rec, "v07", True, False)["feed"], "stale")
            clock(rec, tick="x", tick_seconds=[], next_tick_in={"a": 1}, round="r", next_opens=5, doors=7)
            out = ST.status(rec, "v07", True, False)
            self.assertEqual((out["tick"], out["tick_seconds"], out["seconds_to_tick"], out["round"]), (None, None, None, None))
            clock(rec)
            now = (rec / "latest" / "clock.json").stat().st_mtime
            out = ST.status(rec, "v07", True, False, now=now + 9.0 + 15.0 * 2 + 4.0)   # two whole ticks and 4 s later
            self.assertEqual((out["tick"], out["seconds_to_tick"], out["feed"]), (1449, 11.0, "ok"))
            self.assertEqual(ST.status(rec, "v07", True, False, now=now + 46.0)["feed"], "stale")
            self.assertEqual(ST.status(rec, "v07", False, False, now=now)["market"], "off")
            self.assertEqual(ST.status(rec, "v07", False, False, now=now)["matchmaker"], "waiting")


class CardsTest(Base):
    def test_my_cards_have_the_shape_of_the_fixture(self):
        s7, tok7 = self.verified("t07")
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {
            "wants": [{"ref": "LAT-06", "max": 88, "value": 95}], "spares": ["LAT-03"],
            "for_sale": [{"ref": "LAT-03", "price": 12, "min": 9}], "have": ["LAT-03"]}, tok7)
        self.assertEqual((st, out["limits_saved"], set(out)), (200, 2, {"team", "declared", "limits_saved", "private"}))
        self.assertNotIn("have", out["declared"])
        fx = fixture("me_cards.json")
        for path, headers in (("/plaza/api/me/cards" + s7, None), ("/plaza/api/me/cards", tok7),
                              ("/plaza/api/agent/cards", tok7)):
            st, mine, _ = self.call("GET", path, headers=headers)
            self.assertEqual(st, 200, path)
            self.assertLessEqual(set(fx), set(mine), path)
            self.assertEqual(set(mine["counts"]), set(fx["counts"]))
            self.assertEqual(set(mine["have"][0]), set(fx["have"][1]))             # a card for sale, with its price
            self.assertEqual(set(mine["want"][0]) - {"bid"}, set(fx["want"][1]))
        self.assertEqual({k: v for k, v in mine["have"][0].items() if k != "art"},
                         {"ref": "LAT-03", "name": "Huevos Rotos", "rarity": "common", "set": "LAT", "color": "#F2A541",
                          "owned": True, "as": "for_sale", "price": 12, "by": "agent", "limits": {"min": 9}})
        self.assertEqual((mine["want"][0]["ref"], mine["want"][0]["owned"], mine["want"][0]["finishes_page"],
                          mine["want"][0]["limits"]), ("LAT-06", False, True, {"max": 88, "value": 95}))
        self.assertEqual(mine["counts"], {"have": 1, "duplicates": 1, "for_sale": 1, "want": 1, "limits_set": 2,
                                          "overrides": 0})
        st, me, _ = self.call("GET", "/plaza/api/me", headers=tok7)
        self.assertLessEqual(set(fixture("me.json")), set(me))
        self.assertEqual((me["owned"], me["read_only"], me["venue"], me["status"]["verified"]), (["LAT-03"], False, "v07", True))
        self.assertEqual(set(me["status"]), set(fixture("me.json")["status"]))
        self.assertEqual(set(me["trades"]), set(fixture("me.json")["trades"]))
        self.assertEqual(set(me["settings"]), set(fixture("me_settings.json")))
        self.assertEqual(set(self.call("GET", "/plaza/api/me" + s7)[1]["status"]), set(fixture("me.json")["status"]))

    def test_a_human_override_survives_the_agent_and_is_released(self):
        s7, tok7 = self.verified("t07")
        self.call("PUT", "/plaza/api/team/t07", {"wants": ["LAT-06"], "spares": ["LAT-03"]}, tok7)
        url = "/plaza/api/me/cards" + s7
        st, out, _ = self.call("POST", url, {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": 30, "min": 25})
        self.assertEqual(st, 200, out)
        row = next(c for c in out["have"] if c["ref"] == "LAT-06")
        self.assertEqual((row["as"], row["price"], row["by"], row["limits"]), ("for_sale", 30, "human", {"min": 25}))
        st, out, _ = self.call("POST", url, {"op": "remove", "list": "wants", "ref": "LAT-06"})
        self.assertEqual(([c["ref"] for c in out["want"]], out["counts"]["overrides"]), ([], 3))
        # the agent publishes its whole sheet again, with its own idea of that card: the human's word stays
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {
            "wants": ["LAT-06"], "spares": ["LAT-03"], "for_sale": [{"ref": "LAT-06", "price": 99, "min": 77}]}, tok7)
        self.assertEqual(st, 200)
        mine = self.call("GET", url)[1]
        row = next(c for c in mine["have"] if c["ref"] == "LAT-06")
        self.assertEqual((row["price"], row["by"], row["limits"]), (30, "human", {"min": 25}))
        self.assertEqual(mine["want"], [])
        public = self.call("GET", "/plaza/api/team/t07")[1]                         # and it is what everybody sees
        self.assertEqual([(e["ref"], e.get("price")) for e in public["for_sale"]], [("LAT-06", 30)])
        self.assertEqual(public["wants"], [])
        # released: the agent's sheet is back, and its limit now lands
        for body in ({"op": "release", "list": "for_sale", "ref": "LAT-06"}, {"op": "release", "list": "wants", "ref": "LAT-06"}):
            self.assertEqual(self.call("POST", url, body)[0], 200)
        self.call("PUT", "/plaza/api/team/t07", {"for_sale": [{"ref": "LAT-06", "price": 99, "min": 77}]}, tok7)
        mine = self.call("GET", url)[1]
        row = next(c for c in mine["have"] if c["ref"] == "LAT-06")
        self.assertEqual((row["price"], row["by"], row["limits"]), (99, "agent", {"min": 77}))
        self.assertEqual(([c["ref"] for c in mine["want"]], mine["counts"]["overrides"]), (["LAT-06"], 0))
        # the same call twice changes nothing more
        a = self.call("POST", url, {"op": "add", "list": "spares", "ref": "LAT-06"})[1]
        b = self.call("POST", url, {"op": "add", "list": "spares", "ref": "LAT-06"})[1]
        self.assertEqual((a["have"], a["counts"]), (b["have"], b["counts"]))

    def test_the_agent_edits_one_card_with_its_token(self):
        _, tok7 = self.verified("t07")
        url = "/plaza/api/me/cards"
        st, out, _ = self.call("POST", url, {"op": "add", "list": "wants", "ref": "LAT-06", "bid": 80, "max": 88}, tok7)
        self.assertEqual((st, out["want"][0]["bid"], out["want"][0]["by"], out["want"][0]["limits"]), (200, 80, "agent", {"max": 88}))
        st, out, _ = self.call("POST", url, {"op": "add", "list": "have", "ref": "LAT-03"}, tok7)
        self.assertEqual([(c["ref"], c["as"]) for c in out["have"]], [("LAT-03", "keep")])
        st, out, _ = self.call("POST", url, {"op": "remove", "list": "wants", "ref": "LAT-06"}, tok7)
        self.assertEqual(out["want"], [])
        st, out, _ = self.call("POST", url, {"op": "remove", "list": "have", "ref": "LAT-03"}, tok7)
        self.assertEqual(out["have"], [])

    def test_have_and_limits_never_leave_the_team(self):
        s7, tok7 = self.verified("t07")
        s9, tok9 = self.verified("t09")
        self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 1771, "value": 1881}],
                                                "have": ["LAT-05"]}, tok7)
        self.call("POST", "/plaza/api/me/cards" + s7, {"op": "add", "list": "have", "ref": "LAT-06"})
        self.call("POST", "/plaza/api/me/cards" + s9, {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": 1555,
                                                       "min": 1333, "value": 1991})
        self.call("POST", "/plaza/api/suggestions" + s7, {"text": "more cards"})
        self.assertEqual(self.call("GET", "/plaza/api/me" + s7)[1]["owned"], ["LAT-05", "LAT-06"])
        blob = ""
        for path in ("/plaza/api/teams", "/plaza/api/team/t07", "/plaza/api/team/t09", "/plaza/api/matches",
                     "/plaza/api/wall", "/plaza/api/offers?team=t07", "/plaza/api/floor", "/plaza/api/card/LAT-06",
                     "/plaza/api/status", "/plaza/api/status" + s9):
            blob += json.dumps(self.call("GET", path)[1])
        card = self.call("GET", "/plaza/api/card/LAT-05")[1]                        # the card's own page: no holder
        self.assertEqual((card["holders"], card["seekers"]), ([], []))
        for path in ("/plaza/api/me", "/plaza/api/me/cards", "/plaza/api/me/activity", "/plaza/api/me/settings",
                     "/plaza/api/me/suggestions", "/plaza/api/agent/cards", "/plaza/api/agent/next"):
            st, body, _ = self.call("GET", path, headers=tok9)                      # the other team, with its own token
            self.assertEqual(st, 200, path)
            self.assertFalse(leaks(json.dumps(body), "1771") or leaks(json.dumps(body), "1881"), path)
            self.assertNotIn("LAT-05", json.dumps(body), path)                      # t07 holds it; t09 never hears
        for path in ("/plaza/admin/api/overview", "/plaza/admin/api/activity", "/plaza/admin/api/activity?team=t07",
                     "/plaza/admin/api/activity?team=t09", "/plaza/admin/api/matchmaker"):
            st, body, _ = self.call("GET", path, headers=ADMIN)
            self.assertEqual(st, 200, path)
            blob += json.dumps(body)
        for bad in ({"op": "add", "list": "wants", "ref": "LAT-06", "max": "x"}, {"op": "add", "list": "wants", "ref": "ZZZ-99"},
                    {"max": 99999}):
            blob += json.dumps(self.call("POST", "/plaza/api/me/cards" + s7, bad)[1])
        for secret in ("1771", "1881", "1333", "1991"):
            self.assertFalse(leaks(blob, secret), secret)
        at = blob.find("LAT-05")
        self.assertEqual(at, -1, blob[max(0, at - 300):at + 80])                   # only ever in t07's `have`
        for path in self.live.rglob("*"):                                          # nor in any file our bot can read
            if path.is_file():
                raw = path.read_bytes()
                self.assertNotIn(b"LAT-05", raw, path.name)
                for secret in ("1771", "1881", "1333", "1991"):
                    self.assertFalse(leaks(raw, secret), (path.name, secret))
        for path in (self.live.parent / "plaza_private").iterdir():                # and sealed where it does live
            self.assertNotIn(b"LAT-05", path.read_bytes(), path.name)

    def test_a_team_reads_and_writes_itself_only(self):
        s7, tok7 = self.verified("t07")
        s9, tok9 = self.verified("t09")
        self.assertEqual(self.call("PUT", "/plaza/api/team/t09", {"wants": ["LAT-06"]}, tok7)[:2][0], 403)
        self.assertEqual(self.call("PUT", "/plaza/api/team/t09", {"wants": ["LAT-06"]}, tok7)[1]["error"], "wrong_team")
        self.assertEqual(self.call("PUT", "/plaza/api/team/t10", {"wants": ["LAT-06"]}, tok7)[0], 403)
        self.call("POST", "/plaza/api/me/cards" + s7, {"op": "add", "list": "wants", "ref": "LAT-06", "max": 41})
        self.call("POST", "/plaza/api/me/settings" + s7, {"lang": "es", "paused": True})
        self.call("POST", "/plaza/api/suggestions" + s7, {"text": "a thing of t07"})
        for cred in ({"path": s9, "headers": None}, {"path": "", "headers": tok9}):
            mine = self.call("GET", "/plaza/api/me/cards" + cred["path"], headers=cred["headers"])[1]
            self.assertEqual((mine["team"], mine["want"], mine["have"]), ("t09", [], []))
            self.assertEqual(self.call("GET", "/plaza/api/me" + cred["path"], headers=cred["headers"])[1]["limits"], {})
            st = self.call("GET", "/plaza/api/me/settings" + cred["path"], headers=cred["headers"])[1]
            self.assertEqual((st["team"], st["lang"], st["paused"]), ("t09", "en", False))
            self.assertEqual(self.call("GET", "/plaza/api/me/suggestions" + cred["path"], headers=cred["headers"])[1],
                             {"suggestions": []})
            act = self.call("GET", "/plaza/api/me/activity" + cred["path"], headers=cred["headers"])[1]
            self.assertEqual({i["kind"] for i in act["items"]} - {"match"}, {"connect"})
        # a token wins over a session of another team, and no credential at all is refused on every route
        self.assertEqual(self.call("GET", "/plaza/api/me/cards" + s7, headers=tok9)[1]["team"], "t09")
        for path in ("/plaza/api/me", "/plaza/api/me/cards", "/plaza/api/me/settings", "/plaza/api/me/activity",
                     "/plaza/api/me/suggestions"):
            self.assertEqual(self.call("GET", path)[0], 401, path)
            self.assertEqual(self.call("GET", path, headers=ADMIN)[0], 401, path)   # our panel is no team
            self.assertEqual(self.call("GET", path, headers={"X-Plaza-Token": "x" * 32})[0], 401, path)
            self.assertEqual(self.call("GET", path + "?session=" + "y" * 32)[0], 401, path)
        for path, body in (("/plaza/api/me/cards", {"op": "add", "list": "wants", "ref": "LAT-06"}),
                           ("/plaza/api/me/settings", {"lang": "es"}), ("/plaza/api/suggestions", {"text": "x"}),
                           ("/plaza/api/me/card/LAT-06", {"max": 5})):
            self.assertEqual(self.call("POST", path, body)[0], 401, path)
            self.assertEqual(self.call("POST", path, body, {"X-Plaza-Token": "x" * 32})[0], 401, path)
        fresh = "?session=" + self.call("POST", "/plaza/api/connect/start", {"team": "t08"})[1]["session"]
        for path, body in (("/plaza/api/me/cards", {"op": "add", "list": "wants", "ref": "LAT-06"}),
                           ("/plaza/api/me/settings", {"lang": "es"}), ("/plaza/api/suggestions", {"text": "x"})):
            st, out, _ = self.call("POST", path + fresh, body)                      # started, never proved in the game
            self.assertEqual((st, out["error"]), (403, "not_connected"), path)
        self.assertEqual(self.call("GET", "/plaza/api/me/cards" + fresh)[0], 403)

    def test_a_sheet_counts_only_once_the_team_proved_itself(self):
        """Anyone can start a connection in another team's name: what it publishes is shown to nobody."""
        s = self.call("POST", "/plaza/api/connect/start", {"team": "t08"})[1]
        tok = {"X-Plaza-Token": self.call("POST", "/plaza/api/connect/agent", {"team": "t08", "code": s["connect_code"]})[1]["agent_token"]}
        self.assertEqual(self.call("PUT", "/plaza/api/team/t08", {"wants": ["LAT-06"], "spares": ["LAT-03"]}, tok)[0], 200)
        sheet = self.call("GET", "/plaza/api/team/t08")[1]
        self.assertEqual((sheet["verified"], sheet["wants"], sheet["spares"], sheet["declared_at"]), (False, [], [], None))
        self.assertEqual(self.board.store.declared()["t08"], {**self.board.store.declared()["t08"], "declared": None, "unproved": True})
        self.assertEqual([c["ref"] for c in self.call("GET", "/plaza/api/me/cards", headers=tok)[1]["want"]], ["LAT-06"])   # its own view
        (self.record / "threads" / "th-t08.json").write_text(json.dumps(
            {"id": "x", "kind": "team", "messages": [{"sender": "t08", "text": s["connect_code"]}]}) + "\n")
        self.board.verified_at = 0.0
        self.assertTrue(self.call("GET", "/plaza/api/connect/status?session=" + s["session"])[1]["verified"])
        self.board.stale()
        sheet = self.call("GET", "/plaza/api/team/t08")[1]
        self.assertEqual((sheet["verified"], [w["ref"] for w in sheet["wants"]]), (True, ["LAT-06"]))

    def test_a_limit_moves_once_in_twenty_ticks(self):
        s7, tok7 = self.verified("t07")
        url = "/plaza/api/me/card/LAT-06" + s7
        self.assertEqual(self.call("POST", url, {"max": 50, "value": 60})[0], 200)      # set
        self.assertEqual(self.call("POST", url, {"max": 50})[0], 200)                   # the same number: no move
        self.assertEqual(self.call("POST", url, {"max": 55})[0], 200)                   # moved once
        st, out, _ = self.call("POST", url, {"max": 60})
        self.assertEqual((st, out["error"]), (429, "slow_down"))
        self.assertEqual(self.call("POST", url, {"value": 99})[0], 200)                 # what it is worth is no probe
        st, out, _ = self.call("POST", "/plaza/api/me/cards" + s7, {"op": "add", "list": "wants", "ref": "LAT-06", "max": 70})
        self.assertEqual((st, self.call("GET", "/plaza/api/me/cards" + s7)[1]["want"]), (429, []))   # nothing half done
        self.call("POST", url, {"max": None})
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 61}], "spares": ["LAT-03"]}, tok7)
        self.assertEqual(st, 200)                                                       # the human's field: left alone
        self.call("POST", "/plaza/api/me/cards" + s7, {"op": "release", "list": "wants", "ref": "LAT-06"})
        self.call("PUT", "/plaza/api/team/t07", {"spares": [{"ref": "LAT-03", "min": 5}]}, tok7)
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"spares": [{"ref": "LAT-03", "min": 6}]}, tok7)[0], 200)
        st, out, _ = self.call("PUT", "/plaza/api/team/t07", {"wants": [], "spares": [{"ref": "LAT-03", "min": 7}]}, tok7)
        self.assertEqual((st, out["error"]), (429, "slow_down"))
        self.assertEqual(len(self.call("GET", "/plaza/api/team/t07")[1]["wants"]), 1)   # the sheet was not half written
        with (self.live / "events.jsonl").open("a") as f:                               # twenty ticks later
            f.write(json.dumps({"tick": 30, "type": "settlement", "payload": {"venue": "rastro", "price": 9}}) + "\n")
        self.board.tick_feed()
        self.board.rebuild()
        self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"spares": [{"ref": "LAT-03", "min": 7}]}, tok7)[0], 200)
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=tok7)[1]["have"][0]["limits"], {"min": 7})

    def test_input_is_checked(self):
        s7, tok7 = self.verified("t07")
        for mod in (S, TA):
            patch = mock.patch.object(mod, "WRITES_PER_MIN", 10 ** 6)
            patch.start()
            self.addCleanup(patch.stop)
        url = "/plaza/api/me/cards" + s7
        for bad in ([], "x", 5, {}, {"op": "add"}, {"op": "steal", "list": "wants", "ref": "LAT-06"},
                    {"op": "add", "list": "pins", "ref": "LAT-06"}, {"op": "add", "list": "wants", "ref": "lat-06"},
                    {"op": "add", "list": "wants", "ref": "ZZZ-99"}, {"op": "add", "list": "wants", "ref": "LAT-13"},
                    {"op": "add", "list": "wants", "ref": ["LAT-06"]}, {"op": "add", "list": "wants", "ref": "LAT-06", "x": 1},
                    {"op": "add", "list": "wants", "ref": "LAT-06", "price": 5},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "bid": 5},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "max": 5},
                    {"op": "add", "list": "wants", "ref": "LAT-06", "min": 5},
                    {"op": "add", "list": "have", "ref": "LAT-06", "value": 5},
                    {"op": "remove", "list": "wants", "ref": "LAT-06", "max": 5},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": 0},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": 2001},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": 12.5},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": True},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": "12"},
                    {"op": "add", "list": "for_sale", "ref": "LAT-06", "min": -1},
                    {"op": "add", "list": "wants", "ref": "LAT-06", "bid": 1e30}):
            st, out, _ = self.call("POST", url, bad)
            self.assertEqual((st, out.get("error")), (400, "bad_request"), bad)
            self.assertNotIn("Traceback", json.dumps(out))
        self.assertEqual(self.call("GET", url)[1]["counts"]["overrides"], 0)        # nothing of it was stored
        for bad in ({"wants": ["ZZZ-99"]}, {"have": ["LAT-13"]}, {"have": "LAT-03"}, {"have": ["LAT-03"] * 201},
                    {"wants": [{"ref": "LAT-06", "max": 0}]}, {"spares": [{"ref": "LAT-03", "max": 3}]},
                    {"pin": "1234"}, {"wants": ["LAT-06"], "extra": 1}, [], "x", {},
                    {"for_sale": [{"ref": "LAT-06", "price": 99999}]}, {"wants": [{"ref": "ZZZ-99", "max": 5}]}):
            st, out, _ = self.call("PUT", "/plaza/api/team/t07", bad, tok7)
            self.assertEqual((st, out.get("error")), (400, "bad_request"), bad)
        self.assertEqual(self.call("GET", "/plaza/api/me/cards", headers=tok7)[1]["have"], [])
        for bad in ({}, {"lang": "fr"}, {"paused": "yes"}, {"paused": 1}, {"default_mode": "yolo"}, {"lang": None},
                    {"lang": "es", "theme": "light"}, [], "es"):
            st, out, _ = self.call("POST", "/plaza/api/me/settings" + s7, bad)
            self.assertEqual((st, out.get("error")), (400, "bad_request"), bad)
        for bad in ({}, {"text": ""}, {"text": "   "}, {"text": 5}, {"text": "x", "topic": "spam"}, {"text": "x", "team": "t09"}, []):
            st, out, _ = self.call("POST", "/plaza/api/suggestions" + s7, bad)
            self.assertEqual((st, out.get("error")), (400, "bad_request"), bad)
        for bad in ("?since=x", "?limit=-1", "?since=1.5"):
            self.assertEqual(self.call("GET", "/plaza/api/me/activity" + s7 + bad.replace("?", "&"))[0], 400, bad)


class SettingsActivitySuggestTest(Base):
    def test_settings(self):
        s7, tok7 = self.verified("t07")
        fx = fixture("me_settings.json")
        st, out, _ = self.call("GET", "/plaza/api/me/settings" + s7)
        self.assertEqual((st, out), (200, {**fx, "team": "t07"}))
        st, out, _ = self.call("POST", "/plaza/api/me/settings", {"default_mode": "ask_me", "lang": "es", "paused": True}, tok7)
        self.assertEqual((st, out["default_mode"], out["lang"], out["paused"]), (200, "ask_me", "es", True))
        self.assertLessEqual(set(fx), set(out))
        self.assertEqual(self.board.store.paused_teams(), {"t07"})                  # what the matcher reads
        self.assertEqual(self.call("GET", "/plaza/api/me/settings" + s7)[1]["paused"], True)
        self.assertEqual(self.call("POST", "/plaza/api/me/settings" + s7, {"paused": False})[1]["lang"], "es")
        self.assertEqual(self.board.store.paused_teams(), set())
        self.assertEqual(self.call("GET", "/plaza/api/me", headers=tok7)[1]["settings"]["default_mode"], "ask_me")

    def test_activity_is_the_teams_own_story(self):
        s7, tok7 = self.verified("t07")
        self.call("PUT", "/plaza/api/team/t07", {"wants": [{"ref": "LAT-06", "max": 1771}], "have": ["LAT-03"]}, tok7)
        self.call("POST", "/plaza/api/me/card/LAT-06" + s7, {"value": 1881})
        self.call("POST", "/plaza/api/me/settings" + s7, {"lang": "es"})
        self.call("POST", "/plaza/api/suggestions", {"text": "hello"}, tok7)
        st, act, _ = self.call("GET", "/plaza/api/me/activity" + s7)
        self.assertEqual(st, 200)
        self.assertEqual(set(act), set(fixture("me_activity.json")))
        act["items"] = mine = [i for i in act["items"] if i["by"] != "market"]      # the matches are the deals fork's
        self.assertEqual([(i["kind"], i["by"]) for i in mine],
                         [("connect", "agent"), ("connect", "agent"), ("sync", "agent"), ("limits", "agent"),
                          ("limits", "human"), ("settings", "human"), ("suggestion", "agent")])
        self.assertEqual(act["items"][2]["text"], "published 1 cards it has and 1 it wants")
        self.assertLessEqual({"seq", "ts", "tick", "kind", "by", "text"}, set(act["items"][0]))
        self.assertNotIn("team", act["items"][0])
        self.assertFalse(leaks(json.dumps(act), "1771") or leaks(json.dumps(act), "1881"))   # words, never the numbers
        self.assertGreaterEqual(act["seq"], act["items"][-1]["seq"])
        later = self.call("GET", f"/plaza/api/me/activity{s7}&since={act['items'][4]['seq']}")[1]
        self.assertEqual([i["kind"] for i in later["items"] if i["by"] != "market"], ["settings", "suggestion"])
        self.assertEqual(len(self.call("GET", f"/plaza/api/me/activity{s7}&limit=2")[1]["items"]), 2)
        self.assertGreaterEqual(self.call("GET", "/plaza/api/me", headers=tok7)[1]["activity_seq"], act["seq"])
        again = A.Activity(self.live / "plaza_activity.jsonl")                      # a restart reads the same story
        self.assertEqual([i for i in again.since("t07")["items"] if i["by"] != "market"], act["items"])

    def test_suggestions(self):
        s7, tok7 = self.verified("t07")
        st, a, _ = self.call("POST", "/plaza/api/suggestions" + s7, {"text": "  Show the last   deals ", "topic": "feature"})
        self.assertEqual((st, a), (200, {"id": "s-0001", "status": "open"}))
        st, b, _ = self.call("POST", "/plaza/api/suggestions", {"text": "Show the last deals", "topic": "feature"}, tok7)
        self.assertEqual(b, a)                                                      # the same words: the same id
        st, c, _ = self.call("POST", "/plaza/api/suggestions" + s7, {"text": "x" * 5000})
        self.assertEqual((st, c["id"]), (200, "s-0002"))
        rows = self.call("GET", "/plaza/api/me/suggestions" + s7)[1]["suggestions"]
        self.assertEqual([set(r) for r in rows], [set(fixture("suggestions.json")["suggestions"][0])] * 2)
        self.assertEqual((rows[0]["text"], rows[0]["topic"], rows[0]["reply"], len(rows[1]["text"]), rows[1]["topic"]),
                         ("Show the last deals", "feature", None, 600, "other"))
        box = SG.of(self.board)
        self.assertEqual(box.set("s-0001", "planned", "On the card page today.")["status"], "planned")
        row = self.call("GET", "/plaza/api/me/suggestions" + s7)[1]["suggestions"][0]
        self.assertEqual((row["status"], row["reply"]), ("planned", "On the card page today."))
        for bad in (("s-0001", "later", None), ("s-0001", None, 5), ("s-9999", "done", None)):
            with self.assertRaises(PlazaError):
                box.set(*bad)
        for i in range(4):
            self.assertEqual(self.call("POST", "/plaza/api/suggestions" + s7, {"text": f"idea {i}"})[0], 200)
        st, out, _ = self.call("POST", "/plaza/api/suggestions" + s7, {"text": "one too many"})
        self.assertEqual((st, out["error"]), (429, "slow_down"))
        self.assertEqual(len(SG.Suggest(self.live / "plaza_suggestions.json").all()), 6)   # a restart keeps them


class LimitsOfUseTest(Base):
    def test_per_team_on_top_of_per_client(self):
        _, tok7 = self.verified("t07")
        _, tok9 = self.verified("t09")
        with mock.patch.object(S, "WRITES_PER_MIN", 1000), mock.patch.object(TA, "WRITES_PER_MIN", 5):
            for _ in range(5):
                self.assertEqual(self.call("POST", "/plaza/api/me/settings", {"lang": "es"}, tok7)[0], 200)
            st, out, _ = self.call("POST", "/plaza/api/me/settings", {"lang": "es"}, tok7)
            self.assertEqual((st, out["error"]), (429, "slow_down"))
            self.assertEqual(self.call("PUT", "/plaza/api/team/t07", {"wants": []}, tok7)[0], 429)
            self.assertEqual(self.call("POST", "/plaza/api/me/settings", {"lang": "es"}, tok9)[0], 200)   # another team
        with mock.patch.object(TA, "READS_PER_MIN", 3):
            self.board.team_limiter = TA.Limiter()
            codes = [self.call("GET", "/plaza/api/me/cards", headers=tok7)[0] for _ in range(4)]
            self.assertEqual(codes, [200, 200, 200, 429])


class FuzzTest(Base):
    RUBBISH = [True, 0, -1, 1e308, 10 ** 40, "", "x" * 4000, [], [[]], {}, {"a": {"b": {"c": [1, 2, {"d": None}]}}},
               {"op": None, "list": None, "ref": None}, {"op": ["add"], "list": {"a": 1}, "ref": 5},
               {"op": "add", "list": "wants", "ref": "LAT-06", "max": 10 ** 40},
               {"op": "add", "list": "for_sale", "ref": "LAT-06", "price": float("1e308")},
               {"text": {"a": 1}}, {"text": ["x"]}, {"text": "😀" * 700, "topic": 7}, {"lang": 5}, {"paused": []},
               {"default_mode": {}}, {"min": [], "max": {}, "value": "9"}, {"min": 10 ** 40},
               {"wants": {"ref": "LAT-06"}}, {"wants": [None]}, {"wants": [[]]}, {"wants": [{"ref": None}]},
               {"have": [5]}, {"have": {"a": 1}}, {"for_sale": [{"ref": "LAT-06", "price": []}]},
               {"spares": [{"ref": "LAT-03", "min": "1"}]}, {"wants": ["LAT-06"] * 61}]
    ROUTES = [("POST", "/plaza/api/me/cards"), ("POST", "/plaza/api/me/card/LAT-06"), ("POST", "/plaza/api/me/settings"),
              ("POST", "/plaza/api/suggestions"), ("PUT", "/plaza/api/team/t07")]

    def raw(self, data: bytes) -> bytes:
        with socket.create_connection(self.srv.server_address, timeout=5) as s:
            s.sendall(data)
            s.settimeout(5)
            out = b""
            try:
                while chunk := s.recv(65536):
                    out += chunk
                    if b"\r\n\r\n" in out:
                        break
            except OSError:
                pass
            return out

    def test_rubbish_gets_a_4xx_and_the_server_keeps_serving(self):
        s7, tok7 = self.verified("t07")
        with mock.patch.object(S, "WRITES_PER_MIN", 10 ** 6), mock.patch.object(TA, "WRITES_PER_MIN", 10 ** 6), \
                mock.patch.object(S, "READS_PER_MIN", 10 ** 6), mock.patch.object(SG, "PER_MINUTE", 10 ** 6):
            ok = 0
            for method, path in self.ROUTES:
                for body in self.RUBBISH:
                    for cred in ({"path": path + s7, "headers": None}, {"path": path, "headers": tok7}):
                        st, out, _ = self.call(method, cred["path"], body, cred["headers"])
                        by_pin = method == "PUT" and cred["headers"] is None      # no token: the PIN way, unclaimed
                        self.assertIn(st, (403,) if by_pin else (200, 400, 404), (method, path, body, out))
                        ok += st == 200
                        if st != 200:
                            self.assertEqual(set(out), {"error", "message"}, (path, body))
                            self.assertNotIn("Traceback", out["message"])
                            self.assertNotIn("/Users", out["message"])
                            self.assertLessEqual(len(out["message"]), 200)
            self.assertEqual(ok, 0)                                                 # none of it was taken
            # wrong methods and wrong content
            for method in ("DELETE", "PATCH", "OPTIONS"):
                self.assertEqual(self.call(method, "/plaza/api/me/cards" + s7)[0], 405)
            self.assertEqual(self.call("PUT", "/plaza/api/me/cards" + s7, {"op": "add"})[0], 404)
            self.assertEqual(self.call("POST", "/plaza/api/me/activity" + s7, {})[0], 404)
            self.assertEqual(self.call("POST", "/plaza/api/status", {})[0], 404)
            for query in ("?since=%00", "?limit=999999999999", "?since=-1", "?team=../../etc", "?session=%ff%fe"):
                self.assertIn(self.call("GET", "/plaza/api/me/activity" + query, headers=tok7)[0], (200, 400), query)
            head = (f"POST /plaza/api/me/cards{s7} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                    "Connection: close\r\n")
            for body in (b"\xff\xfe\x00not utf-8", b"{" * 2000, b"[" * 15000, b'{"op": "add", "list": "wants", "ref": "LAT-06"',
                         b"\x00" * 64, b'"\\ud800"'):
                got = self.raw(head.encode() + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
                self.assertRegex(got[:15], rb"HTTP/1\.[01] 400", body[:20])
            got = self.raw(head.encode() + b"Content-Length: 99999\r\n\r\n{}")
            self.assertRegex(got[:15], rb"HTTP/1\.[01] 413")
            got = self.raw(head.replace("application/json", "text/plain").encode() + b"Content-Length: 2\r\n\r\n{}")
            self.assertRegex(got[:15], rb"HTTP/1\.[01] 415")
            got = self.raw(head.encode() + b"Content-Length: nope\r\n\r\n{}")
            self.assertRegex(got[:15], rb"HTTP/1\.[01] 400")
            # and after all of it the team is whole and the server answers
            st, mine, _ = self.call("GET", "/plaza/api/me/cards" + s7)
            self.assertEqual((st, mine["team"]), (200, "t07"))
            self.assertEqual(self.call("GET", "/plaza/api/status")[0], 200)
            self.assertEqual(self.call("GET", "/plaza/api/me", headers=tok7)[0], 200)


class FilesTest(unittest.TestCase):
    """A write that dies half way leaves the store readable; a broken file is read from its copy."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_activity_skips_a_line_cut_short(self):
        log = A.Activity(self.root / "a.jsonl")
        log.add("t07", "sync", "one")
        log.add("t07", "limits", "two", ref="LAT-06", match="m-0123456789", tick=5)
        with (self.root / "a.jsonl").open("a") as f:
            f.write('{"seq": 3, "team": "t07", "kind": "sy')                        # the process died here
        again = A.Activity(self.root / "a.jsonl")
        self.assertEqual([i["text"] for i in again.since("t07")["items"]], ["one", "two"])
        self.assertEqual(again.since("t07")["items"][1], {**again.since("t07")["items"][1], "ref": "LAT-06",
                                                         "match": "m-0123456789", "tick": 5})
        self.assertEqual(again.add("t07", "sync", "three")["seq"], 3)

    def test_activity_refuses_what_is_not_a_line(self):
        log = A.Activity(self.root / "a.jsonl", clock=lambda: 100.0)
        for bad in (("t10x", "sync", "x"), ("t07", "nope", "x"), ("t07", "sync", 5), (None, "sync", "x")):
            self.assertIsNone(log.add(*bad))
        row = log.add("t07", "sync", "x " * 500, by="robot", ref="../etc", match=7, tick=True, secret=1771)
        self.assertEqual((len(row["text"]), row["by"], row["tick"]), (200, "agent", None))
        self.assertEqual(set(row), {"seq", "ts", "kind", "by", "text", "tick"})
        self.assertIsNone(log.add("t07", "sync", "x " * 500))                       # the same line again, right away
        self.assertEqual(log.since("t09"), {"team": "t09", "seq": 0, "items": []})

    def test_activity_is_trimmed(self):
        with mock.patch.object(A, "KEEP", 5), mock.patch.object(A, "TRIM_AT", 8):
            log = A.Activity(self.root / "a.jsonl")
            for i in range(20):
                log.add("t07", "sync", f"line {i}")
            self.assertLessEqual(len((self.root / "a.jsonl").read_text().splitlines()), 8)
            self.assertEqual(A.Activity(self.root / "a.jsonl").since("t07")["items"][-1]["text"], "line 19")

    def test_suggestions_survive_a_broken_file(self):
        box = SG.Suggest(self.root / "s.json")
        box.add("t07", "first")
        box.add("t07", "second")
        (self.root / "s.json").write_text('{"n": 2, "rows": [{"id": "s-00')         # cut short
        again = SG.Suggest(self.root / "s.json")
        self.assertEqual([r["text"] for r in again.all()], ["first"])               # the copy: one write behind
        self.assertEqual(again.add("t07", "third")["id"], "s-0002")
        (self.root / "s.json").write_text('{"n": "x", "rows": [5, {"id": 7}, {"id": "s-0009"}]}')
        self.assertEqual(SG.Suggest(self.root / "s.json").all(), [])


if __name__ == "__main__":
    unittest.main()
