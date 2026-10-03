"""What we know about each rival, across the whole session (persisted to data/live/duel_memory.json).

Per rival alias: every duel we played with them (their offers, ours, result), from which we derive an
archetype (fixed / stepped / tough / mute), the size of their concession steps, how much they move from
first offer to final, whether they concede without waiting for us ("free steps"), and whether they
accept silently.

Per item (scenario): the limits we have seen in each role. Every scenario is played twice with the roles
swapped, so in the second leg the rival's limit is very likely the limit we had in the first leg. We
use it only when the rival's offers are consistent with it.

Only structured numbers are stored. Rival text never enters this memory.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from statistics import mean

from .model import DuelView, surplus

PIE_PRIOR_FRAC = 0.35       # Friday: final margins 20-37 P on limits of ~90-150 P
REMAINING_Q = 0.65          # a stepper's next steps shrink geometrically by this factor


def _default_path() -> Path:
    from .. import config      # lazy: tests pass their own path
    return config.LIVE / "duel_memory.json"


def other(role: str) -> str:
    return "buyer" if role == "seller" else "seller"


class OpponentMemory:
    def __init__(self, path: Path | str | None = None, autosave: bool = True):
        self.path = Path(path) if path else _default_path()
        self.autosave = autosave
        self._lock = threading.RLock()
        self.data: dict = {"duels": {}, "items": {}, "updated": 0}
        try:
            loaded = json.loads(self.path.read_text())
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    # --- writing ----------------------------------------------------------------------------------
    def observe_duel(self, v: DuelView) -> dict:
        """Fold the live state of one duel into memory (idempotent). Returns its record."""
        with self._lock:
            rec = self.data["duels"].setdefault(str(v.id), {
                "duel": v.id, "session": v.session, "item": v.item, "role": v.role, "limit": v.limit,
                "rival": v.rival, "first_seen": v.tick, "deadline": v.deadline_tick, "decay": v.decay,
                "uses_days": v.uses_days, "w": v.w, "offers": [], "ours": [], "status": "live",
            })
            rec["last_seen"] = v.tick
            rec["rounds"] = v.rounds
            seen = {tuple(o) for o in rec["offers"]}
            for m in v.messages:
                if m.price is None:
                    continue
                row = [m.tick, m.price, m.days]
                if m.ours:
                    if row not in rec["ours"]:
                        rec["ours"].append(row)
                elif tuple(row) not in seen:
                    rec["offers"].append(row)
                    seen.add(tuple(row))
            priced = [m for m in v.messages if m.price is not None]
            free = sum(1 for a, b in zip(priced, priced[1:])
                       if not a.ours and not b.ours and surplus(v.role, v.limit, b.price) > surplus(v.role, v.limit, a.price))
            rec["free_steps"] = max(int(rec.get("free_steps", 0)), free)
            if not v.messages and v.rival_offer and not rec["offers"]:
                rec["offers"].append([v.rival_offer.tick, v.rival_offer.price, v.rival_offer.days])
            item = self.data["items"].setdefault(v.item, {"seller": {}, "buyer": {}})
            item[v.role][str(v.id)] = {"limit": v.limit, "session": v.session, "rival": v.rival}
            self.data["updated"] = time.time()
            return rec

    def note_days_reading(self, v: DuelView) -> bool:
        """Log once per session how we read the sign of the days weight (for a human to check).
        Returns True the first time for that session."""
        if not v.uses_days:
            return False
        with self._lock:
            book = self.data.setdefault("days_reading", {})
            key = str(v.session)
            if key in book:
                return False
            book[key] = {"duel": v.id, "tick": v.tick, "your_days_weight": v.w, "days_meaning": v.days_meaning,
                         "signed_weight": v.days_w, "ambiguous": v.days_ambiguous, "reading": v.days_label,
                         "at": time.time()}
            return True

    def record_result(self, duel_id, status: str, price=None, rounds=None, days=None,
                      accepted_by: str | None = None) -> None:
        with self._lock:
            rec = self.data["duels"].get(str(duel_id))
            if rec is None:
                return
            rec.update(status=status, price=price, final_rounds=rounds, final_days=days)
            if accepted_by:
                rec["accepted_by"] = accepted_by
            elif status == "deal" and price is not None:
                ours = [o[1] for o in rec["ours"]]
                theirs = [o[1] for o in rec["offers"]]
                rec["accepted_by"] = "rival" if price in ours and price not in theirs else (
                    "us" if price in theirs else "?")
            self.save()

    def save(self) -> None:
        if not self.autosave:
            return
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, indent=0))
                tmp.replace(self.path)
            except OSError:
                pass

    # --- reading ----------------------------------------------------------------------------------
    @staticmethod
    def _shape(rec: dict) -> dict:
        """Archetype of one duel from the rival's offers, as surplus *to the rival's side* moves."""
        role, limit = rec["role"], rec["limit"]
        s = [surplus(role, limit, p) for _, p, _ in rec["offers"]]   # what each offer gives US
        steps = [b - a for a, b in zip(s, s[1:])]
        n_our = len(rec["ours"])
        out = {"n_offers": len(s), "first_s": s[0] if s else None, "last_s": s[-1] if s else None,
               "steps": steps, "free_steps": 0}
        # Offers they made while still waiting for our answer (they moved without us paying a round).
        out["free_steps"] = int(rec.get("free_steps", 0))
        if not s:
            ticks_seen = (rec.get("last_seen") or 0) - (rec.get("first_seen") or 0)
            out["type"] = "mute" if (n_our >= 3 or ticks_seen >= 4) else "unknown"
        elif len(s) == 1:
            out["type"] = "unknown"
        elif all(abs(x) < 0.5 for x in steps):
            out["type"] = "fixed"
        else:
            pos = [x for x in steps if x > 0]
            avg = mean(pos) if pos else 0.0
            out["type"] = "tough" if avg < 2.0 or (s[0] < 0 and avg < 4.0) else "stepped"
            out["avg_step"] = avg
        return out

    def profile(self, alias: str, exclude: int | None = None) -> dict:
        """Everything we learnt about this alias in other duels (and the live one when exclude=None)."""
        with self._lock:
            recs = [r for k, r in self.data["duels"].items()
                    if r.get("rival") == alias and (exclude is None or int(k) != exclude)]
        if not recs:
            return {"alias": alias, "n_duels": 0, "type": "unknown"}
        shapes = [self._shape(r) for r in recs]
        types = [s["type"] for s in shapes if s["type"] != "unknown"]
        steps = [s["avg_step"] for s in shapes if s.get("avg_step")]
        moves = [s["last_s"] - s["first_s"] for s in shapes if s["n_offers"] >= 2]
        n_off = sum(s["n_offers"] for s in shapes)
        closed = [r for r in recs if r.get("status") in ("deal", "no_deal")]
        silent_acc = [r for r in closed if r.get("status") == "deal" and not r["offers"]]
        return {
            "alias": alias, "n_duels": len(recs),
            "type": max(set(types), key=types.count) if types else "unknown",
            "types": types,
            "avg_step": round(mean(steps), 2) if steps else None,
            "avg_total_move": round(mean(moves), 2) if moves else None,
            "free_step_rate": round(sum(s["free_steps"] for s in shapes) / n_off, 2) if n_off else 0.0,
            "mute_duels": sum(1 for s in shapes if s["type"] == "mute"),
            "deals": sum(1 for r in closed if r.get("status") == "deal"),
            "no_deals": sum(1 for r in closed if r.get("status") == "no_deal"),
            "silent_accepts": len(silent_acc),
        }

    def leg_candidates(self, v: DuelView) -> list[int]:
        """Rival limits suggested by the other leg of the same item (our limit there, other role)."""
        with self._lock:
            item = self.data["items"].get(v.item) or {}
            rows = (item.get(other(v.role)) or {})
            cands = sorted({r["limit"] for k, r in rows.items() if int(k) != v.id})
        # Keep only those that leave a positive pie and that the rival's own offers do not contradict
        # (a seller never offers below cost, a buyer never above value).
        offers = [o.price for o in v.rival_offers()]
        ok = []
        for c in cands:
            pie = surplus(v.role, v.limit, c)
            if pie <= 0:
                continue
            if offers:
                if v.role == "buyer" and min(offers) < c:      # rival is the seller, cost c
                    continue
                if v.role == "seller" and max(offers) > c:     # rival is the buyer, value c
                    continue
            ok.append(c)
        return ok

    def assess(self, v: DuelView) -> dict:
        """Opponent model for one live duel: archetype, bounds on the rival's limit, pie estimate."""
        rec = self.observe_duel(v)
        here = self._shape(rec)
        hist = self.profile(v.rival, exclude=v.id)
        typ = here["type"] if here["type"] != "unknown" else hist.get("type", "unknown")
        offers = v.rival_offers()
        s_offers = [v.surplus(o.price) for o in offers]
        s_best = max(s_offers) if s_offers else None

        # Bounds on the rival's limit from their own offers.
        bound = None
        if offers:
            if v.role == "buyer":
                bound = {"rival_cost_at_most": min(o.price for o in offers)}
            else:
                bound = {"rival_value_at_least": max(o.price for o in offers)}

        cands = self.leg_candidates(v)
        # Only a single consistent candidate counts as known: on Friday one item had several scenarios
        # (Taxi Blanco: seller limits 100 and 61), so several candidates are only a hint for Claude.
        known_limit = cands[0] if len(cands) == 1 else None

        prior = PIE_PRIOR_FRAC * v.limit
        step = here.get("avg_step") or hist.get("avg_step")
        if known_limit is not None:
            pie = surplus(v.role, v.limit, known_limit)
            source = "other_leg"
        elif s_best is None:
            pie = prior
            source = "prior"
        else:
            if typ == "fixed":
                remaining = 1.0
            elif step:
                remaining = step * REMAINING_Q / (1 - REMAINING_Q)
            elif hist.get("avg_total_move"):
                remaining = max(0.0, hist["avg_total_move"])
            else:
                remaining = max(0.0, prior - s_best) * 0.6
            pie = s_best + remaining
            n = len(s_offers)
            pie = (n * pie + prior) / (n + 1) if pie < prior else pie
            pie = max(pie, s_best + 1)
            source = "offers"
        next_s = None
        if s_offers:
            if typ == "fixed":
                next_s = s_offers[-1]
            elif step:
                next_s = min(pie, s_offers[-1] + step)
        return {
            "type": typ, "type_here": here["type"], "history": hist,
            "n_offers": len(s_offers), "offer_surplus": s_offers[-6:], "best_offer_surplus": s_best,
            "avg_step": step, "free_steps_here": here["free_steps"],
            "rival_limit_bound": bound, "other_leg_candidates": cands, "rival_limit_estimate": known_limit,
            "pie_estimate": round(max(1.0, pie), 1), "pie_source": source,
            "next_rival_surplus_estimate": None if next_s is None else round(next_s, 1),
            "rival_days": [o.days for o in offers if o.days is not None][-6:],
        }
