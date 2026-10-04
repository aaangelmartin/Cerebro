"""The table of the three days, round by round, from the recorder's leaderboard.

The server only publishes each team's table mark (negotiating + market). The
table is the weighted mean of the rounds, a round counting by its phase:

    table = (0.5 * R1 + 1 * R2 + phase3 * R3) / (0.5 + 1 + phase3)

so each round is recovered from three cuts: the last one of Friday's round
alone (R1), the first one of Sunday (R3 still empty: the mark through
Saturday, as the organisers recalculated it overnight) and the latest one.

    python tools/global_leaderboard.py            # writes the markdown table
    python tools/global_leaderboard.py --json     # prints the same as JSON
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "bazaar" / "data" / "record" / "leaderboard"
OUT = ROOT / "bazaar" / "docs" / "leaderboard-global.md"
PARTS = ("negotiating", "market")
US = "t10"


def cuts(record: Path = RECORD) -> list[dict]:
    """Every recorded cut that carries teams and rounds, oldest first."""
    rows = []
    for path in sorted(record.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            data = row.get("data") or {}
            teams = data.get("teams") or []
            if isinstance(teams, dict):
                teams = list(teams.values())
            rounds = data.get("rounds") or []
            if not teams or not rounds:
                continue
            rows.append({
                "ts": row.get("ts"), "tick": data.get("tick", row.get("tick")),
                "phase": {r["round"]: float(r.get("phase") or 0) for r in rounds},
                "weight": {r["round"]: float(r.get("weight") or 0) for r in rounds},
                "teams": {t["team"]: t for t in teams if t.get("team")},
            })
    return rows


def _mark(team: dict, part: str) -> float:
    return float(team.get(part) or 0)


def build(rows: list[dict]) -> dict:
    """Round marks, the table now and the table if round 3 ended as it stands."""
    if not rows:
        return {"teams": [], "timeline": [], "phase": 0, "tick": None}
    saturday = [r for r in rows if 2 in r["phase"] and 3 not in r["phase"]]
    sunday = [r for r in rows if 3 in r["phase"]]
    now = rows[-1]
    first3 = sunday[0] if sunday else None
    first2 = saturday[0] if saturday else None      # round 1 closed, round 2 still empty
    phase = now["phase"].get(3, 0.0)
    w12 = now["weight"].get(1, 0.5) + now["weight"].get(2, 1.0)
    w3 = now["weight"].get(3, 1.0)
    teams = []
    for tid, t in now["teams"].items():
        row = {"team": tid, "name": t.get("name") or tid, "table": float(t.get("score") or 0)}
        for part in PARTS:
            r1 = None
            if first2 and tid in first2["teams"]:
                w1, p2 = first2["weight"].get(1, 0.5), first2["phase"].get(2, 0.0)
                r1 = _mark(first2["teams"][tid], part) * (w1 + p2) / w1
            if first3 and tid in first3["teams"]:
                p0 = first3["phase"].get(3, 0.0)
                through2 = _mark(first3["teams"][tid], part) * (w12 + p0) / w12   # R3 empty at that cut
            else:
                through2 = _mark(t, part)
            r2 = (w12 * through2 - 0.5 * r1) / 1.0 if r1 is not None else None
            r3 = (_mark(t, part) * (w12 + phase) - w12 * through2) / phase if phase > 0 else 0.0
            row[part] = {"r1": r1, "r2": r2, "r3": r3, "through2": through2, "now": _mark(t, part),
                         "final": (w12 * through2 + w3 * r3) / (w12 + w3)}
        row["r1"] = None if row["negotiating"]["r1"] is None else sum(row[p]["r1"] for p in PARTS)
        row["r2"] = None if row["negotiating"]["r2"] is None else sum(row[p]["r2"] for p in PARTS)
        row["r3"] = sum(row[p]["r3"] for p in PARTS)
        row["through2"] = sum(row[p]["through2"] for p in PARTS)
        row["final"] = sum(row[p]["final"] for p in PARTS)
        teams.append(row)
    for key in ("r1", "r2", "r3", "through2", "table", "final"):
        order = sorted((t for t in teams if t[key] is not None), key=lambda t: -t[key])
        for i, t in enumerate(order, 1):
            t["rank_" + key] = i
    top = [t["team"] for t in sorted(teams, key=lambda t: -t["table"])[:5]]
    teams.sort(key=lambda t: -t["final"])            # by where each team would end
    if US not in top:
        top.append(US)
    timeline = [{"ts": r["ts"], "tick": r["tick"], "phase": r["phase"].get(3, 0.0),
                 "scores": {tid: float(r["teams"][tid].get("score") or 0) for tid in top if tid in r["teams"]}}
                for r in sunday]
    seen: dict = {}
    for r in timeline:                      # one row per board tick: the recorder reads faster than it refreshes
        seen[r["tick"]] = r
    timeline = list(seen.values())
    # how well the formula fits: the round-3 mark must be the same whichever cut it is read from
    return {"tick": now["tick"], "ts": now["ts"], "phase": phase, "teams": teams, "timeline": timeline, "top": top}


def _f(x, nd=1) -> str:
    if x is None:
        return "—"
    return f"{x + 0.0:.{nd}f}".replace("-0,", "0,").replace(".", ",").replace("-0,0", "0,0")


def _move(t: dict) -> str:
    d = t["rank_table"] - t["rank_final"]
    return "" if not d else f" ▲{d}" if d > 0 else f" ▼{-d}"


def markdown(doc: dict) -> str:
    when = time.strftime("%H:%M", time.localtime(doc["ts"])) if doc.get("ts") else "?"
    out = [
        "# Clasificación global · tres días",
        "",
        f"Corte de las {when} (tick {doc['tick']}). La ronda del domingo cuenta ahora al {_f(doc['phase'] * 100, 0)} %.",
        "",
        "Cada ronda vale 60: 30 de negociación y 30 de mercado. La tabla es la media de las rondas con pesos",
        "viernes 0,5, sábado 1 y domingo según lo jugado. Los 40 puntos de los jueces van aparte.",
        "«Final» es la tabla si la ronda del domingo acabara con sus números de ahora a peso completo.",
        "Las notas por ronda están reconstruidas a partir de la tabla publicada; el sábado incluye la corrección",
        "de mercado que hizo la organización esa noche.",
        "",
        "Ordenada por el resultado final proyectado; la flecha dice cuántos puestos sube o baja cada equipo desde su puesto de ahora.",
        "La clasificación se actualiza cada 20 ticks (5 minutos con ticks de 15 s).",
        "",
        "| # | Equipo | Viernes | Sábado | Domingo (neg · mer) | Tabla ahora | Final si acabara así |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in doc["teams"]:
        name = f"**{t['name']}**" if t["team"] == US else t["name"]
        b = "**" if t["team"] == US else ""
        out.append(
            f"| {t['rank_final']} | {name}{_move(t)} | {_f(t['r1'])} ({t.get('rank_r1', '—')}.º) | {_f(t['r2'])} ({t.get('rank_r2', '—')}.º) | "
            f"{_f(t['r3'])} ({_f(t['negotiating']['r3'])} · {_f(t['market']['r3'])}) ({t['rank_r3']}.º) | "
            f"{_f(t['table'], 2)} ({t['rank_table']}.º) | {b}{_f(t['final'], 2)}{b} |")
    out += ["", "## Hoy, corte a corte", "", "| Hora | Tick | Peso domingo | " + " | ".join(doc["top"]) + " |",
            "|---|---|---|" + "---|" * len(doc["top"])]
    for r in doc["timeline"]:
        hh = time.strftime("%H:%M", time.localtime(r["ts"])) if r.get("ts") else "?"
        out.append(f"| {hh} | {r['tick']} | {_f(r['phase'] * 100, 0)} % | "
                   + " | ".join(_f(r["scores"].get(t), 2) for t in doc["top"]) + " |")
    out += ["", "Para refrescar: `python tools/global_leaderboard.py`.", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    doc = build(cuts())
    if args.json:
        print(json.dumps(doc))
        return
    OUT.write_text(markdown(doc))
    print(OUT)


if __name__ == "__main__":
    main()
