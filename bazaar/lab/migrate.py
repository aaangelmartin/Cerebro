"""One-off migrations of the Lab's live state, run by ``lab.run`` at startup (never by hand).

v2 (2026-10-03, audit fixes): the lesson table written before the feedback loop and the anti-poisoning
rules existed is brought in line with them:

- every lesson gets ``created_lc`` (the corpus live clock now), so its holdout only uses later cases;
- Lab lessons that touch rails, name a team or tell us to trust/accept a team are retired;
- Lab lessons of scope ``global`` above shadow go back to shadow (only a human promotes them);
- seed lessons with fewer than 5 cases cannot be active: they become canary;
- canary/shadow/proposed TTLs restart on the live clock (status_since_lc = now).

A marker in ``config.LAB / "migrations.json"`` makes each migration run once.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from bazaar.lab.common import read_json, write_json
from bazaar.lab.gate import MIN_SEED_N_ACTIVE, foreign_trust, human_only, touches_rails
from bazaar.lab.ingest import Corpus
from bazaar.lab.store import LessonStore, lesson_from_dict, write_notice

NAME = "v2_feedback_poisoning"


def migrate_v2(store: LessonStore, corpus: Corpus) -> dict:
    lc = float(corpus.live_clock or 0.0)
    out = {"retired": [], "to_shadow": [], "to_canary": [], "stamped": 0}
    for l in store.all():
        if l.status == "retired":
            continue
        bt = dict(l.backtest or {})
        changed = False
        if bt.get("created_lc") is None:
            bt["created_lc"] = lc
            bt.setdefault("created_ts", l.updated)
            changed = True
        if l.status in ("proposed", "shadow", "canary"):
            bt["status_since_lc"] = lc
            changed = True
        if changed:
            l = store.upsert(lesson_from_dict({**asdict(l), "backtest": bt}), bump=False)
            out["stamped"] += 1
        if l.created_by == "lab" and (touches_rails(l.rule, l.params) or foreign_trust(l.rule, l.params)):
            store.set_status(l.id, "retired", by="migration",
                             why="Revisión de seguridad: señala a un equipo o toca un raíl.")
            out["retired"].append(l.id)
        elif human_only(l) and l.status in ("canary", "active"):
            store.set_status(l.id, "shadow", by="migration",
                             why="Lección global del Laboratorio: solo una persona puede promoverla.")
            out["to_shadow"].append(l.id)
        elif l.created_by == "seed" and l.status == "active" and (l.n or 0) < MIN_SEED_N_ACTIVE:
            store.set_status(l.id, "canary", by="migration",
                             why=f"Lección semilla con {l.n} casos (< 5): en prueba hasta tener uso real.")
            out["to_canary"].append(l.id)
    for lid in out["to_canary"] + out["to_shadow"]:       # their TTL starts now, on the live clock
        l = store.get(lid)
        bt = {**(l.backtest or {}), "status_since_lc": lc, "status_since": time.time()}
        store.upsert(lesson_from_dict({**asdict(l), "backtest": bt}), bump=False)
    return out


def run(store: LessonStore, corpus: Corpus, lab: Path) -> dict | None:
    """Apply pending migrations once; returns what changed (None when nothing was pending)."""
    path = Path(lab) / "migrations.json"
    done = read_json(path, {}) or {}
    if NAME in done:
        return None
    rep = migrate_v2(store, corpus)
    done[NAME] = {"ts": time.time(), **{k: v for k, v in rep.items()}}
    write_json(path, done)
    write_notice("migration", f"Laboratorio actualizado: {len(rep['to_canary'])} lecciones semilla pasan a prueba, "
                 f"{len(rep['retired'])} retiradas por seguridad, {len(rep['to_shadow'])} vuelven a sombra.",
                 path=Path(lab) / "notices.jsonl", **rep)
    return rep
