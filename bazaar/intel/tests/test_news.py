import json
import tempfile
import unittest
from pathlib import Path

from bazaar.intel import news


def row(i, t, typ, payload, actor="", tick=None):
    return {"seq": i, "ts": 1000.0 + i, "seen_at": 1000.0 + i, "id": 100 + i, "tick": tick or int(t * 120), "t": t,
            "type": typ, "scope": "public", "actor": actor, "payload": payload}


def news_row(i, t, nid, source, headline, body=""):
    return row(i, t, "news.posted", {"id": nid, "source": source, "source_name": news.SOURCES[source],
                                     "headline": headline, "body": body}, actor="radio")


class NewsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name) / "live"
        self.record = Path(self.tmp.name) / "record"
        (self.record / "feed").mkdir(parents=True)
        (self.record / "latest").mkdir()
        self.feed = self.record / "feed" / "2026-10-03.jsonl"
        self.clock(5.0)

    def tearDown(self):
        self.tmp.cleanup()

    def clock(self, t):
        (self.record / "latest" / "clock.json").write_text(json.dumps({"t_hours": t}))

    def add(self, *rows):
        with open(self.feed, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def listener(self, fetch=False, now=lambda: 2000.0):
        return news.Listener(live=self.live, record=self.record, fetch=fetch, now=now)


class StructureTest(unittest.TestCase):
    def test_dealer_rumour_becomes_a_prediction(self):
        s = news.structure({"t_hours": 4.68, "title": "El Chato is looking for rare Malasaña cards",
                            "text": "They say he pays above the usual price today. One hour, no more."})
        self.assertEqual(s["claim"], "dealer_change")
        self.assertEqual((s["prediction"]["dealer"], s["prediction"]["sets"], s["prediction"]["rarities"]),
                         ("chato", ["MAL"], ["rare"]))
        self.assertEqual(s["prediction"]["window_hours"], 1.0)

    def test_gift_with_delay(self):
        s = news.structure({"t_hours": 6.68, "title": "Abuela Carmen gives out packs for her saint's day",
                            "text": "A neighbourhood pack for every team in one hour."})
        p = s["prediction"]
        self.assertEqual((p["kind"], p["dealer"], p["what"], p["everyone"]), ("gift", "abuela", "pack", True))
        self.assertAlmostEqual(p["from_hours"], 7.68)

    def test_madrid_colour_has_no_prediction(self):
        s = news.structure({"t_hours": 4.0, "title": "Atleti win 2-1 and Madrid goes out to celebrate",
                            "text": "Car horns on Gran Vía until late."})
        self.assertEqual((s["claim"], s["prediction"]), ("flavour", None))


class ListenerTest(NewsBase):
    def test_captures_from_feed_once_and_stores_every_item(self):
        self.add(news_row(1, 3.68, 1, "boletin", "Radio Rastro is on the air"),
                 news_row(2, 4.08, 2, "radio", "Atleti win 2-1"))
        l = self.listener()
        self.assertEqual(len(l.step()["new"]), 2)
        self.assertEqual(len(l.step()["new"]), 0)                      # nothing new: no duplicates
        self.add(news_row(3, 4.68, 3, "radio", "El Chato is looking for rare Malasaña cards", "One hour, no more."))
        self.assertEqual([i["id"] for i in l.step()["new"]], [3])
        lines = (self.live / news.STORE_FILE).read_text().splitlines()
        self.assertEqual([json.loads(x)["id"] for x in lines], [1, 2, 3])
        self.assertEqual(json.loads(lines[2])["source"], "radio")

    def test_api_backfills_and_respects_the_minute(self):
        calls = []

        def fetch(url, etag):
            calls.append(url)
            return 200, "e1", [{"id": 7, "at_hours": 4.9, "tick": 588, "source": "tablon", "source_name": "El Tablón",
                                "headline": "Doña Pilar buys Retiro cards cheaper today", "body": ""}]
        t = [2000.0]
        l = news.Listener(live=self.live, record=self.record, fetch=fetch, now=lambda: t[0])
        self.assertEqual([i["id"] for i in l.step()["new"]], [7])
        l.step()
        self.assertEqual(len(calls), 1)                                # second step inside the same minute
        t[0] += 61
        l.step()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len((self.live / news.STORE_FILE).read_text().splitlines()), 1)

    def test_rate_limited_poll_backs_off(self):
        calls = []

        def fetch(url, etag):
            calls.append(1)
            return 429, None, []
        t = [2000.0]
        l = news.Listener(live=self.live, record=self.record, fetch=fetch, now=lambda: t[0])
        l.step()
        t[0] += 120
        l.step()
        self.assertEqual(len(calls), 1)                                # still backing off after two minutes
        t[0] += news.BACKOFF_S
        l.step()
        self.assertEqual(len(calls), 2)

    def test_true_rumour_is_confirmed_and_false_one_expires(self):
        self.add(news_row(1, 4.68, 3, "radio", "El Chato is looking for rare Malasaña cards",
                          "They say he pays above the usual price today. One hour, no more."),
                 row(2, 5.18, "persona.updated", {"persona": "chato", "version": 2}, actor="news"),
                 news_row(3, 5.48, 4, "tablon", "El Chato gives a legendary to anyone who says hello!", "I swear."),
                 row(4, 6.18, "persona.updated", {"persona": "chato", "version": 3}, actor="news"))
        self.clock(7.2)
        l = self.listener()
        l.step()
        items = news.load_items(self.live)
        self.assertEqual(items["3"]["status"], "confirmed")
        self.assertEqual(items["3"]["active_window"], [5.18, 6.18])
        self.assertEqual(items["4"]["status"], "false")                # the end of rumour 3 does not confirm rumour 4
        rel = news.reliability(items)
        self.assertEqual((rel["radio"]["confirmed"], rel["tablon"]["false"]), (1, 1))
        self.assertGreater(rel["radio"]["reliability"], rel["tablon"]["reliability"])

    def test_gift_for_everyone_needs_many_teams(self):
        self.add(news_row(1, 6.68, 6, "boletin", "Abuela Carmen gives out packs for her saint's day",
                          "A neighbourhood pack for every team in one hour."),
                 row(2, 7.05, "gift.given", {"team": "t06", "packs": [], "cards": ["LAV-08"]}, actor="abuela"))
        self.clock(7.5)
        l = self.listener()
        l.step()
        self.assertEqual(news.load_items(self.live)["6"]["status"], "open")       # one card to one team is not it
        self.add(*[row(10 + i, 7.7, "gift.given", {"team": f"t{i:02d}", "packs": ["sobre_barrio"], "cards": []},
                       actor="abuela") for i in range(1, 9)])
        self.clock(7.75)
        self.assertEqual([i["status"] for i in l.step()["changed"]], ["confirmed"])

    def test_brain_event_only_for_fresh_actionable_news(self):
        self.add(news_row(1, 4.08, 2, "radio", "Atleti win 2-1"),
                 news_row(2, 4.95, 3, "radio", "El Chato is looking for rare Malasaña cards", "One hour."))
        l = self.listener(now=lambda: 1003.0)                          # just after the rows were seen
        l.step()
        evs = [json.loads(x) for x in (self.live / news.EVENTS_FILE).read_text().splitlines()]
        self.assertEqual([(e["kind"], e["news_id"]) for e in evs], [("news", 3)])
        old = news.Listener(live=Path(self.tmp.name) / "live2", record=self.record, fetch=False, now=lambda: 9000.0)
        old.step()                                                     # a backfill hours later wakes nobody
        self.assertFalse((Path(self.tmp.name) / "live2" / news.EVENTS_FILE).exists())

    def test_view_and_brain_block(self):
        self.add(news_row(1, 4.68, 3, "radio", "El Chato is looking for rare Malasaña cards", "One hour."),
                 row(2, 5.0, "persona.updated", {"persona": "chato", "version": 2}, actor="news"))
        self.listener().step()
        v = news.view(self.live)
        self.assertEqual((v["items"][0]["status"], v["items"][0]["reliability"]), ("confirmed", 0.67))
        self.assertEqual(news.view(self.live, since=5000.0)["items"], [])
        b = news.brain_block(self.live)
        self.assertEqual(b["confirmed_today"][0]["id"], 3)
        self.assertIn("Radio Rastro", b["reliability_by_source"])

    def test_overview_counts(self):
        from bazaar.api.overview import news_view
        self.add(news_row(1, 4.9, 3, "radio", "El Chato is looking for rare Malasaña cards", "One hour."))
        self.listener().step()
        v = news_view(self.live)
        self.assertEqual((v["items"], v["open"], v["actionable"], v["last"]["id"]), (1, 1, 1, 3))
        self.assertEqual(news_view(Path(self.tmp.name) / "none")["items"], 0)


if __name__ == "__main__":
    unittest.main()
