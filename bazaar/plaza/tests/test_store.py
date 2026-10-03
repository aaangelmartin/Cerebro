"""The plaza store: a team's sheet behind a PIN, never its game key."""
import json
import tempfile
import unittest
from pathlib import Path

from bazaar.plaza.store import PlazaError, Store, clean_refs, clean_sale


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.store = Store(Path(self.dir.name) / "plaza.json", clock=lambda: self.now[0])

    def tearDown(self):
        self.dir.cleanup()

    def test_claim_then_declare(self):
        got = self.store.claim("t04", "4242")
        self.assertFalse(got["verified"])
        self.assertTrue(got["code"].startswith("PLAZA-"))
        d = self.store.declare("t04", "4242", {"wants": ["LAV-07", "LAV-07"], "for_sale": [{"ref": "SAL-09", "price": 60}, "LAT-04"]})
        self.assertEqual(d["wants"], ["LAV-07"])
        self.assertEqual(d["for_sale"], [{"ref": "SAL-09", "price": 60}, {"ref": "LAT-04"}])
        self.assertEqual(self.store.declared()["t04"]["declared"]["wants"], ["LAV-07"])

    def test_a_field_left_out_keeps_its_value(self):
        self.store.claim("t04", "4242")
        self.store.declare("t04", "4242", {"wants": ["LAV-07"], "spares": ["MAL-02"]})
        d = self.store.declare("t04", "4242", {"spares": []})
        self.assertEqual((d["wants"], d["spares"]), (["LAV-07"], []))

    def test_wrong_pin_and_lock(self):
        self.store.claim("t04", "4242")
        for _ in range(5):
            with self.assertRaises(PlazaError) as c:
                self.store.declare("t04", "0000", {"wants": []})
            self.assertEqual(c.exception.code, "bad_pin")
        with self.assertRaises(PlazaError) as c:
            self.store.declare("t04", "4242", {"wants": []})
        self.assertEqual(c.exception.status, 429)
        self.now[0] += 61
        self.assertEqual(self.store.declare("t04", "4242", {"wants": []})["wants"], [])

    def test_unclaimed_and_host_and_bad_input(self):
        for team, code in (("t05", "unclaimed"), ("t10", "host"), ("tXX", "bad_request"), ("../x", "bad_request")):
            with self.assertRaises(PlazaError) as c:
                self.store.declare(team, "4242", {"wants": []})
            self.assertEqual(c.exception.code, code, team)
        self.store.claim("t05", "abcd")
        for body in ({"wants": ["lav-07"]}, {"wants": "LAV-07"}, {"wants": ["LAV-07"] * 61}, {"key": "x"},
                     {"for_sale": [{"ref": "SAL-09", "price": -1}]}, {"for_sale": [{"ref": "SAL-09", "price": True}]}, []):
            with self.assertRaises(PlazaError):
                self.store.declare("t05", "abcd", body)
        for pin in ("1", "has space", "x" * 17, None, 1234):
            with self.assertRaises(PlazaError):
                self.store.claim("t06", pin)

    def test_verified_team_cannot_be_reclaimed(self):
        code = self.store.claim("t04", "4242")["code"]
        self.store.declare("t04", "4242", {"wants": ["LAV-07"]})
        other = self.store.claim("t04", "9999")                 # unverified: a new claim replaces it and its sheet
        self.assertNotEqual(other["code"], code)
        self.assertIsNone(self.store.declared()["t04"]["declared"])
        self.assertFalse(self.store.verify("t04", "hello " + code))     # the old code no longer counts
        self.assertTrue(self.store.verify("t04", f"here: {other['code'].lower()}"))
        with self.assertRaises(PlazaError) as c:
            self.store.claim("t04", "4242")
        self.assertEqual(c.exception.code, "claimed")
        self.assertTrue(self.store.claim("t04", "9999")["verified"])

    def test_nothing_secret_is_stored_in_clear_or_returned(self):
        self.store.claim("t04", "4242")
        raw = (Path(self.dir.name) / "plaza.json").read_text()
        self.assertNotIn("4242", raw)
        self.assertNotIn("pin", json.dumps(self.store.declared()))
        self.assertNotIn("code", json.dumps(self.store.declared()))

    def test_cleaners(self):
        self.assertEqual(clean_refs(None, "wants"), [])
        self.assertEqual(clean_sale([{"ref": "LAV-01", "price": 9.6}]), [{"ref": "LAV-01", "price": 10}])


if __name__ == "__main__":
    unittest.main()
