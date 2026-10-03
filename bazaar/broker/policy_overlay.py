"""Broker policy overlay: the tunable knobs of BenchEngine that el cerebro (and, through it, the Lab) may change.

data/live/broker_policy.json = {"version": "...", "updated": ts, "by": "cerebro", "why": "...", "policy": {...}}

Only the knobs below are accepted, each clamped to hard bounds; anything else (or a bad value) is dropped and
reported. The broker reads the overlay only when no Market Test session is running, so a policy never changes
in the middle of a session, and it logs the overlay version it used in each session's start record.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

CROSS_RULES = ("quotes", "limits", "probe")

# key -> (kind, lo, hi)
TOP_BOUNDS: dict[str, tuple[str, float, float]] = {
    "max_bench_matches_per_tick": ("int", 1, 20),
    "max_probes": ("int", 0, 5),
    "probe_after": ("int", 0, 8),
    "probes_when_quotes": ("int", 0, 3),
    "probe_refusals": ("int", 1, 10),
    "probe_refusal_runs": ("int", 1, 5),
    "hard_traders": ("int", 6, 40),
    "carry_max_weight": ("float", 0.0, 100.0),
}
PROFILE_BOUNDS: dict[str, tuple[str, float, float]] = {
    "prior_shade": ("float", 0.0, 0.6),
    "prior_weight": ("float", 0.0, 50.0),
    "max_shade": ("float", 0.1, 0.9),
    "hazard": ("float", 0.0, 0.8),
    "hazard_weight": ("float", 0.0, 200.0),
    "wait_ticks": ("float", 0.0, 6.0),
    "geo_max_ratio": ("float", 0.3, 1.0),
    "lin_steps": ("float", 0.0, 8.0),
    "stop_ticks": ("int", 1, 8),
    "firm_ticks": ("int", 1, 10),
    "endgame_ticks": ("int", 0, 8),
    "tt_bonus": ("float", 0.0, 10.0),
    "min_weight": ("float", 0.0, 50.0),
    "limit_margin": ("float", 0.0, 0.6),
    "limit_margin_abs": ("float", 0.0, 30.0),
    "limit_conf": ("float", 0.0, 1.0),
}
PROFILES = ("normal", "hard")


def _num(kind: str, v: Any, lo: float, hi: float):
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x < lo or x > hi:          # NaN or out of bounds: rejected, not clamped (a typo must not pass)
        return None
    return int(round(x)) if kind == "int" else round(x, 4)


def validate(raw: Any) -> tuple[dict, list[str]]:
    """(clean overlay, rejected entries). Unknown keys and out-of-bound values are rejected."""
    clean: dict[str, Any] = {}
    rejected: list[str] = []
    if not isinstance(raw, dict):
        return {}, ["overlay is not an object"] if raw not in (None, {}) else []
    for k, v in raw.items():
        if k == "cross_rule":
            if v in CROSS_RULES:
                clean[k] = v
            else:
                rejected.append(f"cross_rule={v!r}")
        elif k == "profiles":
            if not isinstance(v, dict):
                rejected.append("profiles is not an object")
                continue
            for name, prof in v.items():
                if name not in PROFILES or not isinstance(prof, dict):
                    rejected.append(f"profiles.{name}")
                    continue
                for pk, pv in prof.items():
                    b = PROFILE_BOUNDS.get(pk)
                    x = _num(b[0], pv, b[1], b[2]) if b else None
                    if x is None:
                        rejected.append(f"profiles.{name}.{pk}={pv!r}")
                    else:
                        clean.setdefault("profiles", {}).setdefault(name, {})[pk] = x
        elif k in TOP_BOUNDS:
            b = TOP_BOUNDS[k]
            x = _num(b[0], v, b[1], b[2])
            if x is None:
                rejected.append(f"{k}={v!r}")
            else:
                clean[k] = x
        else:
            rejected.append(f"unknown knob {k}")
    return clean, rejected


def version_of(policy: dict) -> str:
    return hashlib.sha1(json.dumps(policy or {}, sort_keys=True).encode()).hexdigest()[:10]


def load(path: Path) -> dict:
    """{"policy": clean, "version", "rejected", "by", "why", "updated"}; empty policy when missing or unreadable."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"policy": {}, "version": version_of({}), "rejected": [], "by": None, "why": None, "updated": None}
    clean, rejected = validate(doc.get("policy") if isinstance(doc, dict) else None)
    return {"policy": clean, "version": version_of(clean), "rejected": rejected,
            "by": doc.get("by") if isinstance(doc, dict) else None,
            "why": doc.get("why") if isinstance(doc, dict) else None,
            "updated": doc.get("updated") if isinstance(doc, dict) else None}


def write(path: Path, policy: dict, by: str, why: str, now: float | None = None) -> dict:
    """Validate and write the overlay atomically. Returns the written doc (with what was rejected)."""
    clean, rejected = validate(policy)
    doc = {"version": version_of(clean), "updated": now or time.time(), "by": by, "why": (why or "")[:600],
           "policy": clean, "rejected": rejected}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    tmp.replace(p)
    return doc


def apply(base: dict, overlay: dict) -> dict:
    """base policy (already merged with defaults) + a clean overlay -> new policy dict (base is not modified)."""
    pol = json.loads(json.dumps(base))
    for k, v in (overlay or {}).items():
        if k == "profiles":
            for name, prof in v.items():
                pol.setdefault("profiles", {}).setdefault(name, {}).update(prof)
        else:
            pol[k] = v
    return pol
