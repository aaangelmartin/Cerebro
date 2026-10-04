"""The plaza store: a team's sheet behind a PIN, never its game key."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bazaar.plaza import connect as C
from bazaar.plaza import private as P
from bazaar.plaza import store as ST
from bazaar.plaza.store import PlazaError, Store, clean_refs, clean_sale, read_json, whole, write_atomic


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.store = Store(Path(self.dir.name) / "plaza.json", clock=lambda: self.now[0])

    def tearDown(self):
        self.dir.cleanup()

    def test_claim_then_declare(self):
        got = self.store.claim("t04", "42424242")
        self.assertFalse(got["verified"])
        self.assertTrue(got["code"].startswith("PLAZA-"))
        d = self.store.declare("t04", "42424242", {"wants": ["LAV-07", "LAV-07"], "for_sale": [{"ref": "SAL-09", "price": 60}, "LAT-04"]})
        self.assertEqual(d["wants"], ["LAV-07"])
        self.assertEqual(d["for_sale"], [{"ref": "SAL-09", "price": 60}, {"ref": "LAT-04"}])
        self.assertEqual((self.store.declared()["t04"]["declared"], self.store.declared()["t04"]["unproved"]), (None, True))
        self.assertTrue(self.store.verify("t04", got["code"]))                # proved in the game: what anybody
        self.assertEqual(self.store.declared()["t04"]["declared"], None)       # could have left before is dropped
        self.assertFalse(self.store.declared()["t04"]["unproved"])
        self.store.declare("t04", "42424242", {"wants": ["LAV-07"]})          # and what the proved team says shows
        self.assertEqual(self.store.declared()["t04"]["declared"]["wants"], ["LAV-07"])

    def test_a_pin_set_before_the_team_connected_dies_with_the_proof(self):
        self.store.claim("t04", "42424242")                                   # anybody, in the team's name
        self.store.declare("t04", "42424242", {"wants": ["LAV-07"]})
        self.store.mark_verified("t04")                                       # the real team proves itself by Connect
        with self.assertRaises(PlazaError) as c:
            self.store.check("t04", "42424242")
        self.assertEqual(c.exception.code, "unclaimed")
        self.assertEqual(self.store.declared()["t04"]["declared"], None)
        with self.assertRaises(PlazaError) as c:
            self.store.claim("t04", "99999999")                               # and nobody sets a new one over it
        self.assertEqual(c.exception.code, "claimed")

    def test_the_guesser_waits_not_the_team(self):
        code = self.store.claim("t04", "42424242", "1.1.1.1")["code"]
        self.store.verify("t04", code)
        for _ in range(5):
            with self.assertRaises(PlazaError):
                self.store.check("t04", "00000000", "6.6.6.6")
        with self.assertRaises(PlazaError) as c:
            self.store.check("t04", "42424242", "6.6.6.6")
        self.assertEqual(c.exception.status, 429)
        self.assertTrue(self.store.check("t04", "42424242", "1.1.1.1")["verified"])   # the team itself goes on

    def test_a_field_left_out_keeps_its_value(self):
        self.store.claim("t04", "42424242")
        self.store.declare("t04", "42424242", {"wants": ["LAV-07"], "spares": ["MAL-02"]})
        d = self.store.declare("t04", "42424242", {"spares": []})
        self.assertEqual((d["wants"], d["spares"]), (["LAV-07"], []))

    def test_wrong_pin_and_lock(self):
        self.store.claim("t04", "42424242")
        for _ in range(5):
            with self.assertRaises(PlazaError) as c:
                self.store.declare("t04", "00000000", {"wants": []})
            self.assertEqual(c.exception.code, "bad_pin")
        with self.assertRaises(PlazaError) as c:
            self.store.declare("t04", "42424242", {"wants": []})
        self.assertEqual(c.exception.status, 429)
        self.now[0] += 61
        self.assertEqual(self.store.declare("t04", "42424242", {"wants": []})["wants"], [])

    def test_unclaimed_and_host_and_bad_input(self):
        for team, code in (("t05", "unclaimed"), ("t10", "host"), ("tXX", "bad_request"), ("../x", "bad_request")):
            with self.assertRaises(PlazaError) as c:
                self.store.declare(team, "42424242", {"wants": []})
            self.assertEqual(c.exception.code, code, team)
        self.store.claim("t05", "abcdefgh")
        for body in ({"wants": ["lav-07"]}, {"wants": "LAV-07"}, {"wants": ["LAV-07"] * 61}, {"key": "x"},
                     {"for_sale": [{"ref": "SAL-09", "price": -1}]}, {"for_sale": [{"ref": "SAL-09", "price": True}]}, []):
            with self.assertRaises(PlazaError):
                self.store.declare("t05", "abcdefgh", body)
        for pin in ("1", "4242", "has space", "x" * 33, None, 12345678):
            with self.assertRaises(PlazaError):
                self.store.claim("t06", pin)

    def test_verified_team_cannot_be_reclaimed(self):
        code = self.store.claim("t04", "42424242")["code"]
        self.store.declare("t04", "42424242", {"wants": ["LAV-07"]})
        other = self.store.claim("t04", "99999999")                 # unverified: a new claim replaces it and its sheet
        self.assertNotEqual(other["code"], code)
        self.assertIsNone(self.store.declared()["t04"]["declared"])
        self.assertFalse(self.store.verify("t04", "hello " + code))     # the old code no longer counts
        self.assertTrue(self.store.verify("t04", f"here: {other['code'].lower()}"))
        with self.assertRaises(PlazaError) as c:
            self.store.claim("t04", "42424242")
        self.assertEqual(c.exception.code, "claimed")
        self.assertTrue(self.store.claim("t04", "99999999")["verified"])

    def test_nothing_secret_is_stored_in_clear_or_returned(self):
        self.store.claim("t04", "42424242")
        raw = (Path(self.dir.name) / "plaza.json").read_text()
        self.assertNotIn("4242", raw)
        self.assertNotIn("pin", json.dumps(self.store.declared()))
        self.assertNotIn("code", json.dumps(self.store.declared()))

    def test_cleaners(self):
        self.assertEqual(clean_refs(None, "wants"), [])
        self.assertEqual(clean_sale([{"ref": "LAV-01", "price": 9.6}]), [{"ref": "LAV-01", "price": 10}])


class FilesTest(unittest.TestCase):
    """Every store writes a temporary file, renames it, keeps the copy it replaced, and reads the copy back."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_write_keeps_the_previous_copy(self):
        path = self.root / "x.json"
        write_atomic(path, b'{"n": 1}')
        self.assertFalse((self.root / "x.json.bak").exists())
        write_atomic(path, b'{"n": 2}', 0o600)
        self.assertEqual((read_json(path), json.loads((self.root / "x.json.bak").read_text())), ({"n": 2}, {"n": 1}))
        self.assertEqual(oct((self.root / "x.json.bak").stat().st_mode)[-3:], "600")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["x.json", "x.json.bak"])    # no stray .tmp

    def test_a_write_killed_half_way_leaves_the_store_readable(self):
        store = Store(self.root / "plaza.json")
        store.verify("t04", store.claim("t04", "42424242")["code"])
        store.declare("t04", "42424242", {"wants": ["LAV-07"]})
        real = os.replace

        def dies(src, dst):                                    # the process dies before the new file is in place
            if str(dst).endswith("plaza.json"):
                raise OSError("killed")
            return real(src, dst)
        with mock.patch.object(ST.os, "replace", dies), self.assertRaises(OSError):
            store.declare("t04", "42424242", {"wants": ["LAV-08"]})
        self.assertEqual(Store(self.root / "plaza.json").declared()["t04"]["declared"]["wants"], ["LAV-07"])
        # the file itself cut short (a full disk, a crash while it was written in place): the copy is read
        (self.root / "plaza.json").write_text('{"teams": {"t04": {"decl')
        again = Store(self.root / "plaza.json")
        self.assertTrue(again.declared()["t04"]["claimed"])
        again.declare("t04", "42424242", {"wants": ["LAV-09"]})                        # and it goes on from there
        self.assertEqual(Store(self.root / "plaza.json").declared()["t04"]["declared"]["wants"], ["LAV-09"])
        for junk in ("", "[]", "null", "\x00\x00"):
            (self.root / "plaza.json").write_text(junk)
            (self.root / "plaza.json.bak").write_text(junk)
            self.assertEqual(Store(self.root / "plaza.json").declared(), {})       # both gone: empty, never a crash

    def test_the_vault_and_the_sessions_read_their_copy_too(self):
        vault = P.Vault(self.root / "private")
        vault.put("t09", "SAL-09", {"min": 50})
        vault.put("t09", "SAL-09", {"value": 70})
        vault.set_have("t09", ["SAL-09", "LAT-02"])
        (self.root / "private" / "limits.bin").write_bytes(b"garbage that is not sealed")
        again = P.Vault(self.root / "private")
        self.assertEqual(again.get("t09"), {"SAL-09": {"min": 50, "value": 70}})   # one write behind, not lost
        self.assertIsNone(again.have("t09"))
        self.assertEqual(oct((self.root / "private" / "limits.bin.bak").stat().st_mode)[-3:], "600")
        conn = C.Connect(self.root / "connect.json")
        a = conn.start("t04", "c1")
        conn.start("t05", "c1")
        (self.root / "connect.json").write_text("{")
        again = C.Connect(self.root / "connect.json")
        self.assertEqual(again.session(a["session"])["team"], "t04")
        (self.root / "connect.json").write_text('{"sessions": [], "agents": 5}')   # the wrong shapes: empty, no crash
        (self.root / "connect.json.bak").unlink()
        self.assertEqual(C.Connect(self.root / "connect.json").overview(), {})


class OverridesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "plaza.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_the_humans_word_wins_and_is_released(self):
        s = self.store
        s.mark_verified("t04")
        s.declare("t04", None, {"wants": ["LAV-07"], "spares": ["MAL-02"], "for_sale": [{"ref": "SAL-09", "price": 60}]})
        s.edit("t04", "add", "for_sale", "MAL-02", True, price=15)
        s.edit("t04", "remove", "wants", "LAV-07", True)
        s.edit("t04", "add", "wants", "RET-03", True, bid=30)
        eff = s.declared()["t04"]["declared"]
        self.assertEqual((eff["wants"], eff["spares"]), (["RET-03"], ["MAL-02"]))
        self.assertEqual(eff["for_sale"], [{"ref": "SAL-09", "price": 60}, {"ref": "MAL-02", "price": 15}])
        s.declare("t04", None, {"wants": ["LAV-07", "LAV-08"], "for_sale": []})    # the agent's whole sheet again
        eff = s.declared()["t04"]["declared"]
        self.assertEqual((eff["wants"], eff["for_sale"]), (["LAV-08", "RET-03"], [{"ref": "MAL-02", "price": 15}]))
        self.assertEqual(s.sheet("t04")["overrides"]["wants"]["RET-03"]["bid"], 30)
        for lst, ref in (("for_sale", "MAL-02"), ("wants", "LAV-07"), ("wants", "RET-03")):
            s.edit("t04", "release", lst, ref, True)
        eff = s.declared()["t04"]["declared"]
        self.assertEqual((eff["wants"], eff["for_sale"]), (["LAV-07", "LAV-08"], []))
        s.edit("t04", "release", "wants", "LAV-07", False)                         # nothing to release: nothing changes
        self.assertEqual(s.declared()["t04"]["declared"]["wants"], ["LAV-07", "LAV-08"])

    def test_the_agent_edits_its_own_list(self):
        s = self.store
        s.edit("t04", "add", "wants", "LAV-07", False, bid=40)
        s.edit("t04", "add", "wants", "LAV-07", False, bid=45)                     # again: one entry, the new bid
        s.edit("t04", "add", "for_sale", "SAL-09", False, price=60)
        sheet = s.sheet("t04")
        self.assertEqual((sheet["effective"]["wants"], sheet["bids"], sheet["effective"]["for_sale"]),
                         (["LAV-07"], {"LAV-07": 45}, [{"ref": "SAL-09", "price": 60}]))
        s.edit("t04", "remove", "wants", "LAV-07", False)
        self.assertEqual((s.sheet("t04")["effective"]["wants"], s.sheet("t04")["bids"]), ([], {}))
        s.edit("t04", "add", "wants", "LAV-08", False, bid=9)
        self.assertNotIn("bids", s.declare("t04", None, {"wants": ["LAV-09"]}))
        self.assertEqual(s.sheet("t04")["bids"], {})                               # a bid goes with its want
        for bad in (("steal", "wants", "LAV-07"), ("add", "pins", "LAV-07"), ("add", "wants", "lav-7"), ("add", "wants", None)):
            with self.assertRaises(PlazaError):
                s.edit("t04", *bad, False)
        with self.assertRaises(PlazaError):
            s.edit("t10", "add", "wants", "LAV-07", False)                         # the host has no sheet
        for i in range(ST.MAX_REFS):
            s.edit("t05", "add", "spares", f"LAV-{i:02d}", False)
        with self.assertRaises(PlazaError):
            s.edit("t05", "add", "spares", "MAL-01", False)

    def test_settings_and_limit_locks(self):
        s = self.store
        self.assertEqual(s.settings("t04"), {"lang": "en", "paused": False})
        self.assertEqual(s.set_settings("t04", lang="es", paused=True), {"lang": "es", "paused": True})
        self.assertEqual(s.set_settings("t04", paused=False), {"lang": "es", "paused": False})
        s.set_settings("t05", paused=True)
        self.assertEqual(s.paused_teams(), {"t05"})
        for bad in ({"lang": "fr"}, {"paused": "yes"}, {"paused": 1}, {"lang": 5}):
            with self.assertRaises(PlazaError):
                s.set_settings("t04", **bad)
        s.lock_limits("t04", "LAV-07", ["min", "nonsense"])
        s.lock_limits("t04", "LAV-07", ["value"])
        self.assertEqual(s.sheet("t04")["overrides"]["limits"], {"LAV-07": ["min", "value"]})
        s.lock_limits("t04", "LAV-07", None)
        self.assertEqual(s.sheet("t04")["overrides"]["limits"], {})
        self.assertNotIn("pin", s.raw("t04"))

    def test_whole_numbers(self):
        self.assertEqual((whole(1, "p"), whole(2000, "p"), whole(12.0, "p")), (1, 2000, 12))
        for bad in (0, 2001, -5, 12.5, True, "12", None, [], float("nan"), float("inf"), 10 ** 40):
            with self.assertRaises(PlazaError):
                whole(bad, "p")


if __name__ == "__main__":
    unittest.main()
