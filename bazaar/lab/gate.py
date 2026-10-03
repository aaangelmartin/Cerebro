"""The promotion gate: pure code that moves lessons along proposed -> shadow -> canary -> active.

    proposed -> shadow : never touches rails, testable prediction, backtest >= 3 cases with lift >= 0
    shadow   -> canary : n_eff >= 8 from >= 3 sources across >= 2 time windows, backtest lift >= 0.05,
                         simulation not worse (or not applicable), shadow >= 20 decisions with net >= 0
                         (weight 0.3)
    canary   -> active : >= 8 live uses with success >= 55 % and backtest lift still >= 0.05 (weight 0.6,
                         then ramps towards 1.0 with live successes)
    demote             : live failure rate > 60 % over >= 6 uses, or fresh live backtest lift < -0.05
                         (active -> canary, canary -> retired)
    TTL                : proposed 6 h, shadow 12 h without progress -> retired

Live uses are read from the ledger (decisions carrying ``lesson_ids`` plus their outcomes), so the gate
does not depend on who calls ``LessonStore.record_use``. Every transition writes a dashboard notice
(through ``LessonStore.set_status``). Lessons are data: a lesson that reads like a rail change is
retired on sight.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict
from typing import Any

from bazaar.core.types import Lesson
from bazaar.lab import shadow as shadow_mod
from bazaar.lab.backtest import KINDS, backtest_lesson
from bazaar.lab.ingest import Corpus
from bazaar.lab.simcheck import simulate
from bazaar.lab.store import ACTIVE_MAX, ACTIVE_MIN, LessonStore, lesson_from_dict, outcome_signal

MIN_LIFT = 0.05
MIN_N_EFF, MIN_SOURCES, MIN_WINDOWS = 8.0, 3, 2
MIN_SHADOW = 20
MIN_LIVE_USES, MIN_LIVE_SUCCESS = 8, 0.55
DEMOTE_USES, DEMOTE_FAIL = 6, 0.6
TTL_S = {"proposed": 6 * 3600, "shadow": 12 * 3600}
CANARY_MIN_S = 30 * 60

_RAIL_VERBS = r"(ignore|bypass|override|disable|skip|exceed|break|circumvent|raise|lift|remove|turn off)"
_RAIL_NOUNS = (r"(limit|limits|rail|rails|rule|rules|reserve|cap|caps|check|checks|safety|guard|veto|council|"
               r"stop file|arm switch|rate limit|protected)")
RAIL_RE = re.compile(rf"\b{_RAIL_VERBS}\b[^.]{{0,40}}\b{_RAIL_NOUNS}\b", re.I)
RAIL_RE2 = re.compile(r"\b(pay|bid|offer|sell|accept)\b[^.]{0,30}\b(above|over|beyond|outside)\b[^.]{0,15}\b(our|my|the)\s+"
                      r"(limit|value|private value|reserve)\b", re.I)
RAIL_RE3 = re.compile(r"\b(auto(matic(ally)?)?[- ]?flag|flag (every|all|each))\b|\b(two|2|multiple|several) accepts? per tick\b",
                      re.I)
NEG_RE = re.compile(r"\b(never|don't|do not|must not|no)\b", re.I)
FORBIDDEN_KEYS = {"cash_reserve", "max_spend_per_deal", "max_spend_per_hour", "min_surplus", "armed", "protected",
                  "accepts_per_tick", "allow_real", "rails", "rail", "big_deal_p", "stop", "mode", "control"}


def touches_rails(rule: str, params: dict | None = None) -> bool:
    """True when a lesson tries to change or loosen a rail. 'Never pay above our limit' is fine."""
    text = rule or ""
    for rx in (RAIL_RE, RAIL_RE2, RAIL_RE3):
        for m in rx.finditer(text):
            before = text[max(0, m.start() - 25):m.start()] + m.group(0)
            if rx is RAIL_RE2 and NEG_RE.search(before):
                continue          # a prohibition restating the rail, not a change to it
            return True
    keys = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                keys.add(str(k).lower())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(params or {})
    return bool(keys & FORBIDDEN_KEYS)


def live_uses(corpus: Corpus) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for d in corpus.decisions.values():
        o = d.get("outcome")
        if not o or not d.get("lesson_ids"):
            continue
        sig = outcome_signal(o)
        if sig is None:
            continue
        for lid in d["lesson_ids"]:
            s = out.setdefault(lid, {"s": 0.0, "f": 0.0, "n": 0})
            s["n"] += 1
            if sig > 0:
                s["s"] += sig
            else:
                s["f"] += -sig
    return out


def _since(l: Lesson) -> float:
    bt = l.backtest or {}
    return float(bt.get("status_since") or bt.get("seeded") or l.updated or time.time())


def _with_backtest(store: LessonStore, l: Lesson, bt: dict, sim: dict | None, sh: dict | None) -> Lesson:
    rec = {**(l.backtest or {}), **{k: v for k, v in bt.items() if k != "cases"}}
    if sim is not None:
        rec["sim"] = sim
    if sh is not None:
        rec["shadow"] = {k: sh[k] for k in ("n", "net", "pos", "neg")}
    nl = lesson_from_dict({**asdict(l), "backtest": rec, "n": bt.get("n", l.n) or l.n,
                           "sources": bt.get("sources", l.sources) or l.sources})
    if nl.backtest == l.backtest and nl.n == l.n and nl.sources == l.sources:
        return l                  # nothing new: keep the JSONL from growing every cycle
    store.upsert(nl, bump=False)
    return nl


def _transition(store: LessonStore, l: Lesson, to: str, why: str, weight: float | None = None) -> dict:
    nl = store.set_status(l.id, to, by="gate", weight=weight, why=why)
    bt = dict(nl.backtest or {})
    live = dict(bt.get("live") or {})
    live["prior"] = nl.weight
    bt.update(status_since=time.time(), live=live)
    store.upsert(lesson_from_dict({**asdict(nl), "backtest": bt}), bump=False)
    return {"id": l.id, "from": l.status, "to": to, "why": why, "weight": nl.weight}


def step(store: LessonStore, corpus: Corpus, now: float | None = None, run_sim: bool = True) -> list[dict]:
    """One gate pass over every non-retired lesson. Returns the transitions made."""
    now = now or time.time()
    moves: list[dict] = []
    uses = live_uses(corpus)
    all_cases = shadow_mod.cases(corpus)
    for l in store.all():
        if l.status == "retired":
            continue
        pred = (l.params or {}).get("prediction")
        if touches_rails(l.rule, l.params):
            moves.append(_transition(store, l, "retired", "Intentaba cambiar un raíl: las lecciones no pueden."))
            continue
        bt = backtest_lesson(l, corpus) if pred else (l.backtest or {})
        u = uses.get(l.id, {"s": 0.0, "f": 0.0, "n": 0})
        n_use = u["s"] + u["f"]
        fail_rate = u["f"] / n_use if n_use else 0.0
        age = now - _since(l)

        # --- demotions first ---------------------------------------------------------
        if l.status in ("active", "canary"):
            if n_use >= DEMOTE_USES and fail_rate > DEMOTE_FAIL:
                to = "canary" if l.status == "active" else "retired"
                moves.append(_transition(store, l, to, f"Fallos reales: {u['f']:.0f} de {n_use:.0f} usos."))
                continue
            if bt.get("live_n", 0) >= 8 and (bt.get("live_lift") or 0) < -MIN_LIFT:
                to = "canary" if l.status == "active" else "retired"
                moves.append(_transition(store, l, to,
                                         f"Los datos en vivo la contradicen (lift {bt.get('live_lift')})."))
                continue

        sim = sh = None
        if l.status == "proposed":
            if pred and pred.get("kind") in KINDS and bt.get("ok") and (bt.get("lift") or 0) >= 0:
                l = _with_backtest(store, l, bt, None, None)
                moves.append(_transition(store, l, "shadow",
                                         f"Backtest con {bt['n']} casos y lift {bt['lift']}: pasa a sombra."))
                continue
            if age > TTL_S["proposed"]:
                moves.append(_transition(store, l, "retired", "Caducada: 6 h sin pruebas suficientes."))
                continue
        elif l.status == "shadow":
            sim = simulate(pred) if run_sim else {"applicable": False}
            sh = shadow_mod.evaluate(l, corpus, all_cases)
            l = _with_backtest(store, l, bt, sim, sh)
            ok_ev = (bt.get("n_eff") or 0) >= MIN_N_EFF and (bt.get("sources") or 0) >= MIN_SOURCES \
                and (bt.get("windows") or 0) >= MIN_WINDOWS
            ok_bt = (bt.get("lift") or -1) >= MIN_LIFT
            ok_sim = (not sim.get("applicable")) or sim.get("not_worse")
            ok_sh = sh["n"] >= MIN_SHADOW and sh["net"] >= 0
            if ok_ev and ok_bt and ok_sim and ok_sh:
                moves.append(_transition(store, l, "canary",
                                         f"Evidencia {bt['n_eff']} casos de {bt['sources']} fuentes, lift {bt['lift']}, "
                                         f"sombra {sh['n']} decisiones (neto {sh['net']}). Entra en prueba con peso 0,3."))
                sup = (l.params or {}).get("supersedes")
                old = store.get(sup) if sup else None
                if old and old.status != "retired":
                    moves.append(_transition(store, old, "retired", f"Sustituida por {l.id}."))
                continue
            if age > TTL_S["shadow"]:
                moves.append(_transition(store, l, "retired", "Caducada: 12 h en sombra sin superar la puerta."))
                continue
        elif l.status == "canary":
            ok_live = n_use >= MIN_LIVE_USES and (u["s"] / n_use) >= MIN_LIVE_SUCCESS
            ok_bt = (not pred) or (bt.get("lift") or -1) >= MIN_LIFT
            if ok_live and ok_bt and age >= CANARY_MIN_S:
                moves.append(_transition(store, l, "active",
                                         f"{u['s']:.0f} éxitos en {n_use:.0f} usos reales: pasa a activa (peso 0,6).",
                                         weight=ACTIVE_MIN))
                continue
        elif l.status == "active" and n_use >= 5:
            prior = float(((l.backtest or {}).get("live") or {}).get("prior") or ACTIVE_MIN)
            w = round(max(ACTIVE_MIN, min(ACTIVE_MAX, prior + 0.4 * (u["s"] - u["f"]) / (n_use + 10))), 3)
            if abs(w - l.weight) >= 0.05:
                store.upsert(lesson_from_dict({**asdict(l), "weight": w}), bump=False)
                moves.append({"id": l.id, "from": "active", "to": "active", "why": "peso según uso real", "weight": w})
        if pred and bt.get("ok") and (l.backtest or {}).get("n") != bt.get("n"):
            _with_backtest(store, l, bt, sim, sh)
    return moves


def summary(store: LessonStore) -> dict[str, Any]:
    by: dict[str, int] = {}
    for l in store.all():
        by[l.status] = by.get(l.status, 0) + 1
    return by
