"""The Laboratory process: observe -> hypothesise -> backtest -> simulate -> shadow -> gate, forever.

    python -m bazaar.lab.run              # loop (separate process; never writes to the game)
    python -m bazaar.lab.run --once       # one full cycle including one Opus hypothesis round, then exit
    python -m bazaar.lab.run --once --no-llm

Every cycle (about one tick): read the new ledger lines, feed every new closed negotiation (with the
lesson ids the operator cited) to ``LessonStore.record_use``, handle novelty (a new dealer gets an
Opus-drafted playbook lesson, 'proposed'; new limits, tick speed, duel decay or error codes update
rules.json and leave a dashboard notice), run the gate. Every 30 minutes, or on novelty, one
hypothesis round, skipped while the corpus has not changed. Heartbeat in config.LAB/lab_status.json.

At startup: an old-schema corpus is rebuilt (Friday + the whole live ledger), limits are seeded from
data/live/known.json, and pending state migrations (``lab.migrate``) run once.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import time
import traceback
from pathlib import Path
from typing import Any

from bazaar import config
from bazaar.lab import gate, migrate, seed
from bazaar.lab.common import read_json, safe_id, write_json
from bazaar.lab.hypothesize import hypothesize
from bazaar.lab.ingest import SCHEMA, Ingestor, build_features, load_or_build, seed_known
from bazaar.lab.store import LessonStore, write_notice

HYPOTHESIS_EVERY_S = 30 * 60
NOVELTY_MIN_GAP_S = 5 * 60
GATE_EVERY_S = 60
LAB_DAY_CAP_USD = float(config.ENV.get("BAZAAR_LAB_DAY_CAP_USD", "6"))
RULE_NOVELTY = {"limits", "tick_seconds", "duel_decay", "announcement", "error_code", "event_type", "venue"}

NOVELTY_TEXT = {
    "dealer": "Nuevo dealer detectado: {key}. El Laboratorio prepara una lección de juego (propuesta).",
    "limits": "Cambian los límites del juego: {detail}.",
    "tick_seconds": "Cambia el ritmo del reloj: {detail}.",
    "duel_decay": "Nueva sesión de duelos con decay {key}: cada ronda pesa distinto.",
    "announcement": "Anuncio con posible cambio de reglas: {detail}.",
    "error_code": "Código de error nuevo del juego: {key}.",
    "event_type": "Tipo de evento nuevo en el feed: {key}.",
    "venue": "Mercado nuevo: {key}.",
}


class Lab:
    def __init__(self, lab: Path | None = None, live: Path | None = None, ask=None, use_llm: bool = True,
                 run_sim: bool = True):
        self.lab = Path(lab or config.LAB)
        self.lab.mkdir(parents=True, exist_ok=True)
        if not (self.lab / "lessons.jsonl").exists():
            seed.seed(lab=self.lab)
        self.store = LessonStore(self.lab / "lessons.jsonl")
        old = read_json(self.lab / "corpus.json") or {}
        rebuilt = bool(old) and int(old.get("schema", 1)) < SCHEMA
        self.corpus = load_or_build(self.lab / "corpus.json")
        self.live = Path(live or config.LIVE)
        seed_known(self.corpus, self.live)
        self.ing = Ingestor(self.corpus, live=self.live, state_path=self.lab / "ingest_state.json")
        self.ask, self.use_llm, self.run_sim = ask, use_llm, run_sim
        self.migration = None
        if rebuilt:
            self.ing.poll()                       # re-read the whole live ledger into the new-schema corpus
            self.apply_closings()
            self.ing.save(self.lab / "corpus.json")
        try:
            self.migration = migrate.run(self.store, self.corpus, self.lab)
        except Exception as e:  # noqa: BLE001 - a failed migration must not stop the Lab
            self.migration = {"error": f"{type(e).__name__}: {e}"[:300]}
        st = read_json(self.lab / "lab_status.json", {}) or {}
        self.last_hyp = float(st.get("last_hypothesis_ts") or 0)
        self.last_hyp_version = st.get("last_hypothesis_version")
        self.last_novel_hyp = 0.0
        self.last_gate = 0.0
        self.day = time.strftime("%Y-%m-%d")
        self.spent_today = float(st.get("spent_today", 0.0)) if st.get("day") == self.day else 0.0
        self.cycles, self.errors = 0, []
        self.last_report: dict[str, Any] | None = st.get("last_hypothesis")
        self.last_moves: list[dict] = []

    # --- pieces ------------------------------------------------------------------
    def _rules_change(self, n: dict) -> None:
        path = self.lab / "rules.json"
        rules = read_json(path, {}) or {}
        if n["kind"] == "limits" and isinstance(n.get("detail"), dict) and n["detail"].get("new"):
            rules["limits"] = {**rules.get("limits", {}), **n["detail"]["new"]}
        if n["kind"] == "tick_seconds":
            rules.setdefault("clock", {})["tick_s_now"] = (n.get("detail") or {}).get("tick_seconds")
        if n["kind"] == "duel_decay":
            rules.setdefault("known", {}).setdefault("decays", [])
            rules["known"]["decays"] = sorted(set(rules["known"]["decays"]) | {float(n["key"])})
        if n["kind"] == "error_code":
            rules.setdefault("known", {}).setdefault("errors", [])
            rules["known"]["errors"] = sorted(set(rules["known"]["errors"]) | {n["key"]})
        rules.setdefault("changes", []).append({"ts": time.time(), "tick": n.get("tick"), "kind": n["kind"],
                                                "key": n["key"], "detail": n.get("detail")})
        rules["changes"] = rules["changes"][-200:]
        rules["updated"] = time.time()
        write_json(path, rules)

    def handle_novelty(self) -> list[dict]:
        handled, new_dealers = [], []
        for n in self.corpus.novelty:
            if n.get("handled"):
                continue
            n["handled"] = True
            detail = json.dumps(n.get("detail"), ensure_ascii=False, default=str)[:160]
            write_notice("novelty", NOVELTY_TEXT.get(n["kind"], "Novedad: {key}").format(key=n["key"], detail=detail),
                         path=self.lab / "notices.jsonl", novelty=n["kind"], key=n["key"], tick=n.get("tick"))
            if n["kind"] in RULE_NOVELTY:
                self._rules_change(n)
            if n["kind"] == "dealer" and safe_id(n.get("key")):          # only game-like ids reach Opus
                new_dealers.append(n)
            handled.append(n)
        if new_dealers and self._can_spend() and time.time() - self.last_novel_hyp > NOVELTY_MIN_GAP_S:
            focus = {"new_dealers": [{"id": n["key"], "first_tick": n.get("tick")} for n in new_dealers],
                     "task": "Draft one playbook lesson per new dealer (scope dealer:<id>) from its first threads, "
                             "quotes and prices: opening vs final, how it concedes, what it buys/sells, quotas."}
            self._hypothesize(focus)
            self.last_novel_hyp = time.time()
        elif any(n["kind"] in ("limits", "duel_decay") for n in handled) and self._can_spend() \
                and time.time() - self.last_novel_hyp > NOVELTY_MIN_GAP_S:
            self._hypothesize({"rule_change": [n["key"] for n in handled]})
            self.last_novel_hyp = time.time()
        return handled

    def _can_spend(self) -> bool:
        if time.strftime("%Y-%m-%d") != self.day:
            self.day, self.spent_today = time.strftime("%Y-%m-%d"), 0.0
        return self.use_llm and self.spent_today < LAB_DAY_CAP_USD

    def apply_closings(self) -> int:
        """record_use for every closed negotiation not applied yet (the Lab, not the trading loop, moves weights)."""
        n = 0
        for c in self.corpus.closings.values():
            if c.get("applied"):
                continue
            if c.get("lesson_ids"):
                self.store.record_use(list(c["lesson_ids"]), c)
                n += 1
            c["applied"] = True
        return n

    def _hypothesize(self, focus: dict | None = None) -> dict:
        rep = hypothesize(self.corpus, self.store, focus=focus, ask=self.ask,
                          log_path=self.lab / "hypotheses.jsonl")
        self.spent_today += float(rep.get("cost_usd") or 0.0)
        self.last_hyp = time.time()
        self.last_hyp_version = self.corpus.version
        self.last_report = {k: rep.get(k) for k in ("ts", "model", "cost_usd", "error", "focus")} | {
            "accepted": [a["id"] for a in rep.get("accepted", [])], "rejected": len(rep.get("rejected", []))}
        if rep.get("accepted"):
            write_notice("hypotheses", f"El Laboratorio propone {len(rep['accepted'])} lecciones nuevas (aún sin usar).",
                         path=self.lab / "notices.jsonl", ids=self.last_report["accepted"])
        return rep

    def heartbeat(self, extra: dict | None = None) -> dict:
        feats_counts = {"threads": len(self.corpus.threads), "duels": len(self.corpus.duels),
                        "settlements": len(self.corpus.settlements), "decisions": len(self.corpus.decisions),
                        "leaderboard": len(self.corpus.leaderboard)}
        st = {"updated": time.time(), "pid": os.getpid(), "cycles": self.cycles, "max_tick": self.corpus.max_tick,
              "lessons": gate.summary(self.store), "corpus": feats_counts, "offsets": self.ing.offsets,
              "last_hypothesis_ts": self.last_hyp, "last_hypothesis": self.last_report, "day": self.day,
              "last_hypothesis_version": self.last_hyp_version, "corpus_version": self.corpus.version,
              "live_clock_s": round(self.corpus.live_clock, 1), "closings": len(self.corpus.closings),
              "migration": self.migration, "ingest_errors": self.ing.errors[-5:],
              "spent_today": round(self.spent_today, 4), "day_cap": LAB_DAY_CAP_USD,
              "pending_novelty": sum(1 for n in self.corpus.novelty if not n.get("handled")),
              "last_moves": self.last_moves[-10:], "errors": self.errors[-5:], **(extra or {})}
        write_json(self.lab / "lab_status.json", st)
        return st

    # --- the cycle -------------------------------------------------------------------
    def cycle(self, force_hypothesis: bool = False) -> dict:
        self.cycles += 1
        out: dict[str, Any] = {}
        try:
            out["ingested"] = self.ing.poll()
            out["record_use"] = self.apply_closings()
            out["novelty"] = [n["key"] for n in self.handle_novelty()]
            due = time.time() - self.last_hyp >= HYPOTHESIS_EVERY_S and self.corpus.version != self.last_hyp_version
            if (force_hypothesis or due) and self._can_spend():
                out["hypothesis"] = self._hypothesize()
            if force_hypothesis or time.time() - self.last_gate >= GATE_EVERY_S:
                self.last_moves = gate.step(self.store, self.corpus, run_sim=self.run_sim)
                self.last_gate = time.time()
                out["moves"] = self.last_moves
            self.ing.save(self.lab / "corpus.json")
        except Exception as e:  # noqa: BLE001 - the Lab must never die on bad data
            self.errors.append({"ts": time.time(), "error": f"{type(e).__name__}: {e}"[:300],
                                "trace": traceback.format_exc()[-800:]})
            out["error"] = self.errors[-1]["error"]
        self.heartbeat()
        return out

    def interval(self) -> float:
        ts = self.corpus.seen.get("tick_seconds") or 30.0
        return max(5.0, min(60.0, float(ts)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one cycle with one hypothesis round, then exit")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-sim", action="store_true")
    args = ap.parse_args()
    lab = Lab(use_llm=not args.no_llm, run_sim=not args.no_sim)
    if args.once:
        out = lab.cycle(force_hypothesis=not args.no_llm)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    while not stop["now"]:
        lab.cycle()
        end = time.time() + lab.interval()
        while time.time() < end and not stop["now"]:
            time.sleep(0.5)
    lab.heartbeat({"stopped": time.time()})


if __name__ == "__main__":
    main()
