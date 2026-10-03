"""Shadow: replay the operator's own decisions with a candidate lesson and record what would have happened.

Cases are our duels (Friday + live), our dealer threads (Friday memory + live feed) and the live ledger
decisions in the lesson's scope. For each case the lesson's prediction kind gives a counterfactual
delta (points for duels, primas for dealers; conservative: only half of a price improvement is
credited, since the dealer might not have gone there). Kinds without a counterfactual count as 0, so
"shadow net >= 0" then means "never seen to hurt".
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from bazaar import config
from bazaar.core.types import Lesson
from bazaar.lab.ingest import Corpus

DOMAIN_SCOPE = {"duels": "duel", "market": "market", "broker": "broker"}


def _scope_ok(scope: str, case_scope: str) -> bool:
    if scope == "global" or scope == case_scope:
        return True
    return scope == "dealer" and case_scope.startswith("dealer:")


def cases(corpus: Corpus) -> list[dict]:
    out = []
    for d in corpus.duels.values():
        out.append({"key": f"duel:{d['origin']}:{d['id']}", "scope": "duel", "type": "duel", "rec": d})
    for t in corpus.threads.values():
        if t.get("team") == "t10" and t.get("dealer"):
            out.append({"key": f"thr:{t['origin']}:{t['id']}", "scope": f"dealer:{t['dealer']}", "type": "thread", "rec": t})
    for d in corpus.decisions.values():
        if not d.get("outcome") or d.get("domain") in ("duels", "dealers"):
            continue          # duels and dealer threads are covered above, as whole negotiations
        sc = DOMAIN_SCOPE.get(d.get("domain") or "", "global")
        out.append({"key": f"dec:{d['id']}", "scope": sc, "type": "decision", "rec": d})
    return out


def _margin(d: dict, price: float) -> float:
    return (d["limit"] - price) if d["role"] == "buyer" else (price - d["limit"])


def would_have(lesson: Lesson, case: dict) -> float:
    pred = (lesson.params or {}).get("prediction") or {}
    kind, rec = pred.get("kind"), case["rec"]
    if case["type"] == "duel" and rec.get("limit") is not None:
        decay = rec.get("decay") or 0.06
        realised = rec["points"] if rec["status"] == "deal" else 0.0
        rp = rec.get("rival_prices") or []
        if kind == "duel_accept_first" and rp:
            m1 = _margin(rec, rp[0])
            if m1 >= float(pred.get("min_margin_frac", 0.15)) * rec["limit"]:
                return round(m1 * (1 - decay) - realised, 2)
        if kind == "duel_fast" and rp:
            k = int(pred.get("max_rounds", 3))
            if rec["status"] != "deal" or rec["rounds"] > k:
                best = max((_margin(rec, p) for p in rp[:max(1, k)]), default=0.0)
                if best > 0:
                    return round(best * (1 - decay) ** k - realised, 2)
        if kind == "rival_rate" and pred.get("rival_kind") == "fixed" and rec.get("kind") == "fixed" and rp:
            m = _margin(rec, rp[0])
            if m > 0 and rec["rounds"] > 2:
                return round(m * (1 - decay) ** 2 - realised, 2)
        return 0.0
    if case["type"] == "thread" and kind == "dealer_price" and pred.get("dealer") == rec.get("dealer") \
            and pred.get("side") == rec.get("side"):
        lo, hi = float(pred["lo"]), float(pred["hi"])
        deal = rec.get("deal_price")
        if deal is not None:
            if rec["side"] == "sell" and deal > hi:
                return round((deal - hi) * 0.5, 2)
            if rec["side"] == "buy" and deal < lo:
                return round((lo - deal) * 0.5, 2)
        return 0.0
    return 0.0


def evaluate(lesson: Lesson, corpus: Corpus, all_cases: list[dict] | None = None) -> dict[str, Any]:
    rows = []
    for c in all_cases if all_cases is not None else cases(corpus):
        if not _scope_ok(lesson.scope, c["scope"]):
            continue
        rows.append((c["key"], would_have(lesson, c)))
    deltas = [d for _, d in rows]
    return {"n": len(rows), "net": round(sum(deltas), 2), "pos": sum(1 for d in deltas if d > 0),
            "neg": sum(1 for d in deltas if d < 0),
            "worst": sorted(((k, d) for k, d in rows if d < 0), key=lambda x: x[1])[:5],
            "best": sorted(((k, d) for k, d in rows if d > 0), key=lambda x: -x[1])[:5]}


def record(lesson: Lesson, result: dict, path: Path | None = None) -> None:
    path = Path(path or config.LAB / "shadow.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "lesson_id": lesson.id, "version": lesson.version, **result},
                           ensure_ascii=False, default=str) + "\n")
