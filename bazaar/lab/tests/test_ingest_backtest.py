import json
import tempfile
import unittest
from pathlib import Path

from bazaar.core.types import Lesson
from bazaar.lab.backtest import backtest_lesson, diversity, evaluate
from bazaar.lab.ingest import Corpus, Ingestor, build_features, classify_rival, load_friday


_IDS = iter(range(50_000, 10**9))


def msg(tick, thread, team, dealer, sender, give, want, final=False, eid=None):
    return {"id": eid or next(_IDS), "tick": tick, "type": "thread.message", "actor": sender,
            "payload": {"thread": thread, "kind": "persona", "sender": sender, "team": team, "with": dealer,
                        "text": "hola" if sender == dealer else None,
                        "offer": {"give": give, "want": want, "final": final}}}


def dealer_sale(tick, thread, team, price, ref="LAV-06", final=False):
    return msg(tick, thread, team, "chato", "chato", {"types": [f"card:{ref}"]}, {"cash": price}, final)


def team_bid(tick, thread, team, price, ref="LAV-06"):
    return msg(tick, thread, team, "chato", team, {"cash": price}, {"types": [f"card:{ref}"]})


class FridayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = load_friday(Corpus())
        cls.f = build_features(cls.c)

    def test_friday_corpus_counts(self):
        self.assertGreater(len(self.c.threads), 20)
        self.assertEqual(len(self.c.duels), 25)
        self.assertGreater(len(self.c.leaderboard), 10)
        self.assertEqual(self.f["novelty"], [])         # Friday is the baseline

    def test_dealer_curves(self):
        cur = self.f["dealer_curves"]["chato|buy|uncommon"]
        self.assertEqual(cur["open_med"], 13)
        self.assertGreaterEqual(cur["teams"], 3)
        ab = self.f["dealer_curves"]["abuela|sell|uncommon"]
        self.assertEqual(ab["final_range"], [21, 24])

    def test_duel_stats_fast_beats_slow(self):
        d = self.f["duels"]
        self.assertGreater(d["fast_points"], d["slow_points"])
        self.assertAlmostEqual(d["public"]["deal_rate"], 0.443, places=2)

    def test_attribution_has_clean_classes(self):
        classes = self.f["attribution"]["classes"]
        self.assertTrue(any(k.startswith("dealer_sell") for k in classes))
        self.assertTrue(all(v["n"] >= 1 for v in classes.values()))

    def test_backtest_kinds(self):
        r = evaluate({"kind": "dealer_price", "dealer": "chato", "side": "buy", "item": "uncommon",
                      "stage": "last", "lo": 13, "hi": 16}, self.c)
        self.assertTrue(r["ok"])
        self.assertEqual(r["hit"], 1.0)
        self.assertGreater(r["lift"], 0)
        r = evaluate({"kind": "duel_fast", "max_rounds": 3}, self.c)
        self.assertGreater(r["lift"], 0.05)
        bad = evaluate({"kind": "dealer_price", "dealer": "chato", "side": "buy", "item": "uncommon",
                        "stage": "last", "lo": 40, "hi": 50}, self.c)
        self.assertEqual(bad["hit"], 0.0)
        self.assertFalse(evaluate({"kind": "made_up"}, self.c)["ok"])
        self.assertFalse(evaluate(None, self.c)["ok"])

    def test_backtest_lesson_record(self):
        l = Lesson(id="t", scope="duel", rule="x", params={"prediction": {"kind": "duel_accept_first",
                                                                          "min_margin_frac": 0.15}})
        rec = backtest_lesson(l, self.c)
        for k in ("hit", "lift", "n_eff", "sources", "windows", "live_n"):
            self.assertIn(k, rec)


class DiversityTest(unittest.TestCase):
    def test_single_team_capped_at_two(self):
        c = Corpus()
        for i in range(10):
            c.evidence[f"e{i}"] = {"src": "t05", "tick": i * 40, "w": f"live:{i}", "origin": "live"}
        d = diversity([f"e{i}" for i in range(10)], c)
        self.assertEqual(d["n_eff"], 2.0)
        self.assertEqual(d["sources"], 1)

    def test_each_source_capped_at_two(self):
        c = Corpus()
        srcs = ["t01"] * 6 + ["t02", "t03", "t04"]
        for i, s in enumerate(srcs):
            c.evidence[f"e{i}"] = {"src": s, "tick": 1, "w": "live:0", "origin": "live"}
        d = diversity([f"e{i}" for i in range(9)], c)
        self.assertEqual(d["n_eff"], 2 + 3.0)


class LiveIngestTest(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.lab = Path(tempfile.mkdtemp())

    def write(self, name, rows):
        with open(self.live / name, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_incremental_offsets_and_new_dealer(self):
        c = Corpus()
        ing = Ingestor(c, live=self.live, state_path=self.lab / "st.json")
        self.write("events.jsonl", [team_bid(10, 1, "t03", 80, "LAV-09"), dealer_sale(10, 1, "t03", 97, "LAV-09")])
        self.assertEqual(ing.poll()["events.jsonl"], 2)
        self.assertEqual(ing.poll()["events.jsonl"], 0)            # nothing re-read
        self.write("events.jsonl", [{"id": 9, "tick": 12, "type": "persona.open_to_all",
                                     "payload": {"persona": "vault", "name": "La Bóveda", "level": 3}}])
        ing.poll()
        self.assertTrue(any(n["kind"] == "dealer" and n["key"] == "vault" for n in c.novelty))
        t = c.threads["live:thr:1"]
        self.assertEqual(t["side"], "sell")
        self.assertEqual(t["rarity"], "rare")
        ing.save(self.lab / "corpus.json")
        ing2 = Ingestor(Corpus(json.loads((self.lab / "corpus.json").read_text())), live=self.live,
                        state_path=self.lab / "st.json")
        self.assertEqual(ing2.poll().get("events.jsonl"), 0)

    def test_replayed_feed_is_deduplicated(self):
        c = load_friday(Corpus())
        n = len(c.threads), len(c.settlements)
        ing = Ingestor(c, live=self.live, state_path=self.lab / "st.json")
        src = Path(__file__).resolve().parents[2] / "data" / "friday" / "bot" / "history" / "events.jsonl"
        (self.live / "events.jsonl").write_text(src.read_text())
        ing.poll()
        self.assertEqual((len(c.threads), len(c.settlements)), n)
        self.assertFalse(any(t["origin"] == "live" for t in c.threads.values()))

    def test_partial_line_waits(self):
        c = Corpus()
        ing = Ingestor(c, live=self.live, state_path=self.lab / "st.json")
        with open(self.live / "events.jsonl", "w") as f:
            f.write(json.dumps(dealer_sale(1, 2, "t01", 30)) + "\n" + '{"id": 5, "tick"')
        self.assertEqual(ing.poll()["events.jsonl"], 1)
        with open(self.live / "events.jsonl", "a") as f:
            f.write(': 2, "type": "announcement", "payload": {"text": "hi"}}\n')
        self.assertEqual(ing.poll()["events.jsonl"], 1)

    def test_limits_change_is_novelty(self):
        c = Corpus()
        ing = Ingestor(c, live=self.live, state_path=self.lab / "st.json")
        lim = {"accepts_per_team_per_tick": 1}
        self.write("events.jsonl", [{"id": 1, "tick": 1, "type": "clock.changed", "payload": {"limits": lim}},
                                    {"id": 2, "tick": 5, "type": "clock.changed",
                                     "payload": {"limits": {"accepts_per_team_per_tick": 2}}}])
        ing.poll()
        self.assertTrue(any(n["kind"] == "limits" for n in c.novelty))

    def test_decisions_outcomes_join(self):
        c = Corpus()
        ing = Ingestor(c, live=self.live, state_path=self.lab / "st.json")
        self.write("decisions.jsonl", [{"id": 1, "tick": 3, "action": {"id": "a1", "kind": "duel_accept", "domain": "duels",
                                                                        "params": {}, "expected": {"points": 10},
                                                                        "lesson_ids": ["L01"]},
                                        "verdict": {"ok": True}, "source": "opus"}])
        self.write("outcomes.jsonl", [{"id": 1, "action_id": "a1", "tick": 4, "status": "deal",
                                       "realised": {"points_delta": 7}},
                                      {"id": 2, "action_id": "a2", "tick": 4, "status": "refused",
                                       "response": {"error": "brand_new_error"}}])
        ing.poll()
        e = build_features(c)["errors"]["duels"]
        self.assertEqual(e["bias"], 3.0)
        self.assertTrue(any(n["kind"] == "error_code" for n in c.novelty))

    def test_classify_rival(self):
        self.assertEqual(classify_rival([], "buyer"), "mute")
        self.assertEqual(classify_rival([97, 97, 97], "seller"), "fixed")
        self.assertEqual(classify_rival([89, 98, 110], "seller"), "stepped")
        self.assertEqual(classify_rival([200, 199, 199, 198], "buyer"), "tough")


if __name__ == "__main__":
    unittest.main()
