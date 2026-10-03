import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from bazaar.intel import official as off


def kit_zip(rules: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bazaar-kit/RULES.md", rules)
        z.writestr("bazaar-kit/README.md", "readme")
    return buf.getvalue()


RULES = """# Rules

## Duels (the tournament)
Answer every duel. No deal scores zero.

## Scoring
| Share | What counts |
|---|---|
| Negotiating 30 | dealer ladder and duels |
| Market-making 30 | Market Test efficiency |
"""


def world(**over):
    w = {
        "/bazaar-kit.zip": kit_zip(RULES),
        "/api/schedule": {"now_hours": 4.0, "upcoming": [
            {"at_hours": 5.0, "action": "bench", "note": "The Market Test", "params": {}},
            {"at_hours": 5.15, "action": "duels", "note": "Duels I", "params": {"name": "Duels I"}}]},
        "/api/levels": {"levels": [{"id": "chato", "kind": "persona", "name": "El Chato", "state": "active",
                                    "teaser": "t", "how": "buys rares", "open_to_all": True}]},
        "/api/dealers": {"personas": [{"id": "abuela", "name": "Abuela Carmen", "status": "active", "level": 1,
                                       "open_to_all": True, "menu": {"sells": [{"rarity": "common", "list_price": 10}]}}]},
        "/api/catalog": {"sets": [{"id": "LAV", "name": "Lavapiés", "released": True, "release": "+0h",
                                   "cards": [{"id": "LAV-01", "rarity": "common", "book": 10, "minted": 3}]},
                                  {"id": "CHA", "name": "Chamberí", "released": False, "release": "sun+0h", "cards": []}],
                         "rarities": {"common": {"book": 10, "print_run": 300}}},
        "/api/clock": {"tick": 300, "tick_seconds": 30.0, "paused": False, "doors": "open", "round": 2,
                       "round_name": "Saturday", "limits": {"accepts_per_team_per_tick": 1, "offers_per_team_per_tick": 12},
                       "days": []},
        "/api/news": {"news": []},
        "/api/venues": {"venues": [{"venue": "rastro", "name": "El Rastro", "owner": "world", "status": "open",
                                    "fee_bps": 500, "fee_per_card": 1, "house": True, "trades": 3},
                                   {"venue": "v07", "name": "Team 10", "owner": "t10", "status": "open",
                                    "fee_bps": 0, "fee_per_card": 0, "trades": 0}]},
        "/openapi.json": {"paths": {"/api/clock": {"get": {}}}},
    }
    w.update(over)
    return w


class FakeServer:
    def __init__(self, w):
        self.w = w
        self.calls = []

    def __call__(self, url, headers):
        path = url.replace(off.BASE, "")
        self.calls.append((path, dict(headers)))
        body = self.w[path]
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        etag = '"' + off.sha(raw) + '"'
        if headers.get("If-None-Match") == etag:
            return 304, {"etag": etag}, b""
        return 200, {"etag": etag}, raw


def fetcher(server):
    return off.Fetcher(opener=server, min_gap=0, sleep=lambda s: None)


class OfficialWatcherTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_first_run_is_a_baseline_and_writes_a_digest(self):
        evs = off.run_once(self.dir, fetcher(FakeServer(world())))
        self.assertEqual([e["kind"] for e in evs], ["baseline"])
        digest = (self.dir / off.DIGEST_FILE).read_text()
        self.assertIn("untrusted data", digest)
        self.assertIn("Scoring", digest)
        self.assertIn("El Chato", digest)
        self.assertIn("CHA (from sun+0h)", digest)
        self.assertLessEqual(len(digest), off.DIGEST_CAP)

    def test_unchanged_sources_use_conditional_gets_and_emit_nothing(self):
        srv = FakeServer(world())
        off.run_once(self.dir, fetcher(srv))
        srv.calls.clear()
        self.assertEqual(off.run_once(self.dir, fetcher(srv)), [])
        self.assertTrue(all("If-None-Match" in h for _, h in srv.calls))

    def test_changes_become_events(self):
        off.run_once(self.dir, fetcher(FakeServer(world())))
        w = world()
        w["/bazaar-kit.zip"] = kit_zip(RULES.replace("Negotiating 30", "Negotiating 40"))
        w["/api/schedule"] = {"now_hours": 5.1, "upcoming": [
            {"at_hours": 5.15, "action": "duels", "note": "Duels I", "params": {}},
            {"at_hours": 5.5, "action": "persona_opens", "note": "Doña Pilar opens for everyone", "params": {"persona": "pilar"}}]}
        w["/api/levels"] = {"levels": w["/api/levels"]["levels"] + [
            {"id": "pilar", "kind": "persona", "name": "Doña Pilar", "state": "announced", "teaser": "collector"}]}
        w["/api/clock"] = dict(w["/api/clock"], limits={"accepts_per_team_per_tick": 2, "offers_per_team_per_tick": 12})
        w["/api/news"] = {"news": [{"id": 1, "headline": "Rumour: MAL prices up", "body": "b", "source_name": "Radio Rastro", "tick": 300}]}
        w["/api/venues"] = {"venues": w["/api/venues"]["venues"][:1] + [dict(w["/api/venues"]["venues"][1], fee_bps=100)]}
        w["/api/catalog"] = {"sets": [w["/api/catalog"]["sets"][0], dict(w["/api/catalog"]["sets"][1], released=True)],
                             "rarities": w["/api/catalog"]["rarities"]}
        kinds = {e["kind"] for e in off.run_once(self.dir, fetcher(FakeServer(w)))}
        self.assertTrue({"rules_changed", "schedule_changed", "new_level", "limits_changed", "news",
                         "venue_changed", "set_released"} <= kinds, kinds)
        lines = (self.dir / off.EVENTS_FILE).read_text().splitlines()
        rules = [json.loads(l) for l in lines if json.loads(l)["kind"] == "rules_changed"][0]
        self.assertIn("Negotiating 40", rules["diff_excerpt"])

    def test_schedule_items_that_happened_are_not_news(self):
        off.run_once(self.dir, fetcher(FakeServer(world())))
        w = world()
        w["/api/schedule"] = {"now_hours": 5.1, "upcoming": [w["/api/schedule"]["upcoming"][1]]}
        self.assertEqual(off.run_once(self.dir, fetcher(FakeServer(w))), [])

    def test_untrusted_text_is_cleaned(self):
        self.assertEqual(off.clean("a‮b\x00c"), "abc")
        self.assertTrue(off.clean("x" * 50, 10).endswith("…"))

    def test_a_failing_source_does_not_stop_the_others(self):
        srv = FakeServer(world())
        del srv.w["/api/news"]
        off.run_once(self.dir, fetcher(srv))
        state = json.loads((self.dir / off.STATE_FILE).read_text())
        self.assertIn("clock", state["sources"])
        self.assertTrue(any(e.startswith("news") for e in state["errors"]))


if __name__ == "__main__":
    unittest.main()
