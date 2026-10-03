"""Backtest: check a lesson's falsifiable prediction against the corpus (Friday + live).

A prediction is a small dict with a ``kind`` from ``KINDS`` (the hypothesis prompt shows Opus this
list). Every kind turns the corpus into cases, says per case whether the prediction hit, and
compares with a naive baseline, so ``lift = hit - baseline_hit`` (absolute) except where noted.

Evidence diversity (anti-poisoning) is computed here from the cases' sources and time windows: each
source counts for at most 2 effective cases (a settlement's source is the pair of parties), and the
lift is recomputed with the top source removed (``lift_wo_top``). The gate needs ``n_eff >= 8`` from
``>= 3`` sources across ``>= 2`` windows, and lift >= 0.05 both with and without the top source.

Holdout: ``backtest_lesson`` also evaluates only live cases first seen after the lesson was created
(``holdout_n``, ``holdout_lift``), measured on the corpus' live clock (``lc``, seconds of live play,
robust to tick renumbering); promotion to canary needs that, so no lesson is judged on the data it was
fitted to.
"""
from __future__ import annotations

import statistics as st
from collections import Counter
from typing import Any, Callable

from bazaar.lab.common import book_of, rarity_of, window_of
from bazaar.lab.ingest import Corpus, _med, _mirror_ratios, deal_class

KINDS: dict[str, str] = {
    "dealer_price": '{"kind":"dealer_price","dealer":"abuela","side":"sell|buy (the DEALER\'s side)","item":"common|uncommon|rare|pack:sobre_barrio|*","stage":"open|final|deal|last","lo":21,"hi":24}',
    "mirror_ratio": '{"kind":"mirror_ratio","dealer":"chato","side":"sell|buy","item":"*","lo":0.3,"hi":0.7}  (dealer concession / our concession per exchange)',
    "settlement_price": '{"kind":"settlement_price","where":"rastro|dealer:<id>|any","item":"common|LAV-09|pack:sobre_plata","lo":5,"hi":9}',
    "listing_price": '{"kind":"listing_price","side":"ask|bid","item":"uncommon","lo":25,"hi":40}',
    "duel_fast": '{"kind":"duel_fast","max_rounds":3}  (deals closed within max_rounds score above the median deal)',
    "duel_accept_first": '{"kind":"duel_accept_first","min_margin_frac":0.15}  (accepting the rival\'s first offer when its margin >= frac*limit beats what we realised)',
    "rival_rate": '{"kind":"rival_rate","rival_kind":"mute|fixed|stepped|tough","outcome":"deal|no_deal","lo":0.0,"hi":0.4}',
    "score_delta": '{"kind":"score_delta","class_prefix":"dealer_buy:pack:sobre_plata","sign":-1}  (leaderboard jump after one public deal of that class; classes look like dealer_buy|dealer_sell|team_buy|team_sell:<rarity>:over_book|under_book)',
}
MIN_CASES = 3
SOURCE_CAP = 2.0          # effective cases one source can contribute


class Filter:
    """Which cases count: all, one origin ('friday' | 'live'), or live cases seen after a live-clock mark."""

    def __init__(self, origin: str | None = None, after_lc: float | None = None):
        self.origin, self.after_lc = origin, after_lc

    def ok(self, rec: dict) -> bool:
        if self.origin is not None and rec.get("origin") != self.origin:
            return False
        if self.after_lc is not None:
            lc = rec.get("lc")
            return isinstance(lc, (int, float)) and lc > self.after_lc
        return True


def _flt(origin) -> Filter:
    return origin if isinstance(origin, Filter) else Filter(origin)


def _stage_value(t: dict, stage: str) -> float | None:
    dp = t["dealer_prices"]
    if not dp:
        return None
    if stage == "open":
        return dp[0][1]
    if stage == "final":
        return dp[-1][1] if t["final"] else None
    if stage == "deal":
        return t["deal_price"]
    return dp[-1][1]


def _item_ok(want: str, rarity: str | None, item: str | None = None) -> bool:
    if want in ("*", "", None):
        return True
    return want == rarity or want == item or (want.startswith("pack:") and rarity == want)


def diversity(case_eids: list[str], corpus: Corpus) -> dict[str, Any]:
    srcs, wins = [], set()
    for eid in case_eids:
        e = corpus.evidence.get(eid) or {}
        srcs.append(e.get("src") or "?")
        wins.add(e.get("w") or window_of(e.get("tick"), e.get("origin", "live")))
    n = len(case_eids)
    count = Counter(srcs)
    n_eff = sum(min(SOURCE_CAP, k) for k in count.values())
    return {"n": n, "sources": len(count), "windows": len(wins), "n_eff": round(n_eff, 2),
            "top_source_share": round(max(count.values()) / n, 3) if n else 0.0}


def _default_lift(hits: list[bool], base: list[bool]) -> Callable[[list[int]], float | None]:
    aligned = len(base) == len(hits)

    def f(idx: list[int]) -> float | None:
        if not idx:
            return None
        h = sum(hits[i] for i in idx) / len(idx)
        if aligned:
            b = sum(base[i] for i in idx) / len(idx)
        elif base:
            b = sum(base) / len(base)
        else:
            return None
        return round(h - b, 3)
    return f


def _without_top(eids: list[str], corpus: Corpus, lift_fn: Callable[[list[int]], float | None]) -> float | None:
    """The lift recomputed without the cases of the source that supplied most of them."""
    srcs = [(corpus.evidence.get(e) or {}).get("src") or "?" for e in eids]
    if len(set(srcs)) < 2:
        return None
    top = Counter(srcs).most_common(1)[0][0]
    return lift_fn([i for i, s in enumerate(srcs) if s != top])


def _result(kind: str, hits: list[bool], base: list[bool], eids: list[str], corpus: Corpus,
            lift: float | None = None, extra: dict | None = None,
            lift_fn: Callable[[list[int]], float | None] | None = None) -> dict[str, Any]:
    n = len(hits)
    hit = round(sum(hits) / n, 3) if n else None
    bh = round(sum(base) / len(base), 3) if base else None
    if lift is None and hit is not None and bh is not None:
        lift = round(hit - bh, 3)
    fn = lift_fn or _default_lift(hits, base)
    out = {"kind": kind, "hit": hit, "baseline_hit": bh, "lift": lift, "cases": eids[:40],
           "lift_wo_top": _without_top(eids, corpus, fn) if n else None,
           **diversity(eids, corpus), **(extra or {})}
    out["ok"] = n >= MIN_CASES
    if not out["ok"]:
        out["note"] = f"only {n} cases"
    return out


def _origin_ok(origin, rec: dict) -> bool:
    return _flt(origin).ok(rec)


def evaluate(pred: dict | None, corpus: Corpus, origin: str | Filter | None = None,
             after_lc: float | None = None) -> dict[str, Any]:
    """Evaluate one prediction. ``origin`` restricts to 'friday' or 'live' cases; ``after_lc`` to live cases
    first seen after that live-clock mark (the holdout)."""
    if after_lc is not None:
        origin = Filter("live", float(after_lc))
    if not isinstance(pred, dict) or pred.get("kind") not in KINDS:
        return {"kind": (pred or {}).get("kind") if isinstance(pred, dict) else None, "ok": False, "n": 0,
                "hit": None, "lift": None, "note": "no falsifiable prediction"}
    fn: Callable = _EVAL[pred["kind"]]
    try:
        return fn(pred, corpus, _flt(origin))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        return {"kind": pred["kind"], "ok": False, "n": 0, "hit": None, "lift": None, "note": f"bad prediction: {e!r}"}


def _num(pred: dict, k: str) -> float:
    return float(pred[k])


def _dealer_price(p, c, origin):
    lo, hi = _num(p, "lo"), _num(p, "hi")
    width = max(1.0, hi - lo)
    hits, base, eids = [], [], []
    for t in c.threads.values():
        if not _origin_ok(origin, t) or t.get("dealer") != p.get("dealer") \
                or t.get("side") != p.get("side"):
            continue
        if not _item_ok(p.get("item", "*"), t.get("rarity"), t.get("item")):
            continue
        v = _stage_value(t, p.get("stage", "final"))
        if v is None:
            continue
        hits.append(lo <= v <= hi)
        anchor = (book_of(t.get("item") or "") or v) if p.get("stage") == "open" else t["dealer_prices"][0][1]
        base.append(abs(v - anchor) <= width / 2)
        eids.append(f"thr:{t['origin']}:{t['id']}")
    return _result("dealer_price", hits, base, eids, c)


def _mirror(p, c, origin):
    lo, hi = _num(p, "lo"), _num(p, "hi")
    width = max(0.05, hi - lo)
    hits, base, eids = [], [], []
    for t in c.threads.values():
        if not _origin_ok(origin, t) or t.get("dealer") != p.get("dealer"):
            continue
        if p.get("side") and t.get("side") != p.get("side"):
            continue
        if not _item_ok(p.get("item", "*"), t.get("rarity"), t.get("item")):
            continue
        for r in _mirror_ratios(t):
            hits.append(lo <= r <= hi)
            base.append(abs(r - 1.0) <= width / 2)
            eids.append(f"thr:{t['origin']}:{t['id']}")
    return _result("mirror_ratio", hits, base, eids, c)


def _settlement(p, c, origin):
    lo, hi = _num(p, "lo"), _num(p, "hi")
    width = max(1.0, hi - lo)
    where = p.get("where", "any")
    hits, base, eids = [], [], []
    for s in c.settlements:
        if not _origin_ok(origin, s) or s.get("price") is None or len(s["refs"]) != 1:
            continue
        if where == "rastro" and s.get("venue") != "rastro":
            continue
        if where.startswith("dealer:") and s.get("persona") != where.split(":", 1)[1]:
            continue
        ref = s["refs"][0]
        if not _item_ok(p.get("item", "*"), rarity_of(ref), ref):
            continue
        v = s["price"]
        hits.append(lo <= v <= hi)
        b = book_of(ref) or v
        base.append(abs(v - b) <= width / 2)
        eids.append(s.get("eid") or f"set:{s['origin']}:{s['id']}")
    return _result("settlement_price", hits, base, eids, c)


def _listing(p, c, origin):
    lo, hi = _num(p, "lo"), _num(p, "hi")
    width = max(1.0, hi - lo)
    side = p.get("side", "ask")
    hits, base, eids = [], [], []
    for l in c.listings:
        if not _origin_ok(origin, l):
            continue
        refs, price = (l["ask_refs"], l["ask"]) if side == "ask" else (l["bid_refs"], l["bid"])
        if not refs or not price:
            continue
        if not _item_ok(p.get("item", "*"), rarity_of(refs[0]), refs[0]):
            continue
        hits.append(lo <= price <= hi)
        b = book_of(refs[0]) or price
        base.append(abs(price - b) <= width / 2)
        eid = f"lst:{l['origin']}:{l['tick']}:{l['maker']}:{refs[0]}"
        c.evidence.setdefault(eid, {"src": l.get("maker") or "?", "tick": l["tick"],
                                    "w": window_of(l["tick"], l["origin"]), "origin": l["origin"]})
        eids.append(eid)
    return _result("listing_price", hits, base, eids, c)


def _duels(c, origin):
    return [d for d in c.duels.values() if _origin_ok(origin, d)]


def _duel_fast(p, c, origin):
    k = int(p.get("max_rounds", 3))
    deals = [d for d in _duels(c, origin) if d["status"] == "deal"]
    if not deals:
        return _result("duel_fast", [], [], [], c)
    med = st.median(d["points"] for d in deals)
    hits, eids = [], []
    for d in deals:
        hits.append(d["points"] >= med if d["rounds"] <= k else d["points"] < med)
        eids.append(f"duel:{d['origin']}:{d['id']}")
    fast = [d["points"] for d in deals if d["rounds"] <= k]
    allp = [d["points"] for d in deals]
    rel = round((sum(fast) / len(fast) - sum(allp) / len(allp)) / max(1.0, sum(allp) / len(allp)), 3) if fast else None
    hit = sum(hits) / len(hits)
    return _result("duel_fast", hits, [], eids, c, lift=round(hit - 0.5, 3),
                   extra={"baseline_hit": 0.5, "rel_gain": rel, "median_points": med},
                   lift_fn=lambda idx: round(sum(hits[i] for i in idx) / len(idx) - 0.5, 3) if idx else None)


def _margin(d: dict, price: float) -> float:
    return (d["limit"] - price) if d["role"] == "buyer" else (price - d["limit"])


def _duel_accept_first(p, c, origin):
    frac = float(p.get("min_margin_frac", 0.15))
    hits, eids, af, real = [], [], [], []
    for d in _duels(c, origin):
        if not d["rival_prices"] or d["limit"] is None:
            continue
        m1 = _margin(d, d["rival_prices"][0])
        if m1 < frac * d["limit"]:
            continue
        pts_first = m1 * (1 - (d.get("decay") or 0.06)) ** 1
        realised = d["points"] if d["status"] == "deal" else 0.0
        hits.append(pts_first >= realised - 1e-9)
        af.append(pts_first)
        real.append(realised)
        eids.append(f"duel:{d['origin']}:{d['id']}")
    lift = round((sum(af) - sum(real)) / max(1.0, sum(real)), 3) if real else None

    def lf(idx):
        if not idx:
            return None
        a, r = sum(af[i] for i in idx), sum(real[i] for i in idx)
        return round((a - r) / max(1.0, r), 3)
    return _result("duel_accept_first", hits, [], eids, c, lift=lift, lift_fn=lf,
                   extra={"mean_accept_first": round(sum(af) / len(af), 2) if af else None,
                          "mean_realised": round(sum(real) / len(real), 2) if real else None})


def _rival_rate(p, c, origin):
    kind, outc = p.get("rival_kind"), p.get("outcome", "deal")
    lo, hi = float(p.get("lo", 0.0)), float(p.get("hi", 1.0))
    ds = _duels(c, origin)
    sel = [d for d in ds if d["kind"] == kind]
    if not sel:
        return _result("rival_rate", [], [], [], c)
    rate = sum(1 for d in sel if d["status"] == outc) / len(sel)
    rate_all = sum(1 for d in ds if d["status"] == outc) / len(ds)
    inside = lo <= rate <= hi
    hits = [inside] * len(sel)

    def lift_of(r: float) -> float:
        ins = lo <= r <= hi
        return round(abs(r - rate_all), 3) if ins and not (lo <= rate_all <= hi) else (0.0 if ins else -0.1)
    lift = lift_of(rate)

    def lf(idx):
        if not idx:
            return None
        return lift_of(sum(1 for i in idx if sel[i]["status"] == outc) / len(idx))
    return _result("rival_rate", hits, [], [f"duel:{d['origin']}:{d['id']}" for d in sel], c, lift=lift, lift_fn=lf,
                   extra={"rate": round(rate, 3), "rate_all": round(rate_all, 3)})


def _score_delta(p, c, origin):
    sign = 1 if float(p.get("sign", 1)) > 0 else -1
    prefix = p.get("class_prefix", "")
    deltas = {}
    for case in _attribution_cases(c, origin):
        deltas[case["eid"]] = (case["class"], case["delta"])
    hits, base, eids = [], [], []
    for eid, (klass, delta) in deltas.items():
        base.append((delta > 0) == (sign > 0) and delta != 0)
        if klass.startswith(prefix):
            hits.append((delta > 0) == (sign > 0) and delta != 0)
            eids.append(eid)
    return _result("score_delta", hits, base, eids, c)


def _attribution_cases(c: Corpus, origin):
    flt = _flt(origin)
    snaps = [s for s in c.leaderboard if flt.ok(s)]
    out = []
    for a, b in zip(snaps, snaps[1:]):
        if a["origin"] != b["origin"] or b["tick"] <= a["tick"]:
            continue
        idle, rows = [], []
        for tid, tb in b["teams"].items():
            ta = a["teams"].get(tid)
            if not ta or tb.get("score") is None or ta.get("score") is None:
                continue
            dd = (tb.get("deals") or 0) - (ta.get("deals") or 0)
            if dd == 0:
                idle.append(tb["score"] - ta["score"])
            rows.append((tid, tb["score"] - ta["score"], dd))
        drift = _med(idle) or 0.0
        for tid, delta, dd in rows:
            acts = [e for e in c.team_events.get(tid, []) if e[1] == a["origin"] and a["tick"] < e[0] <= b["tick"]
                    and e[2] in ("deal_dealer", "deal_team")]
            if dd == 1 and len(acts) == 1:
                eid = f"lb:{a['origin']}:{a['tick']}-{b['tick']}:{tid}"
                c.evidence.setdefault(eid, {"src": tid, "tick": b["tick"], "w": window_of(b["tick"], a["origin"]),
                                            "origin": a["origin"]})
                out.append({"eid": eid, "class": deal_class(acts[0]), "delta": round(delta - drift, 3)})
    return out


_EVAL = {
    "dealer_price": _dealer_price, "mirror_ratio": _mirror, "settlement_price": _settlement,
    "listing_price": _listing, "duel_fast": _duel_fast, "duel_accept_first": _duel_accept_first,
    "rival_rate": _rival_rate, "score_delta": _score_delta,
}


def backtest_lesson(lesson, corpus: Corpus) -> dict[str, Any]:
    """Full backtest record stored in ``Lesson.backtest`` (keeps the live use stats)."""
    pred = (lesson.params or {}).get("prediction")
    allr = evaluate(pred, corpus)
    live = evaluate(pred, corpus, origin="live") if allr.get("ok") else {"n": 0}
    rec = {k: allr.get(k) for k in ("kind", "hit", "baseline_hit", "lift", "n", "n_eff", "sources", "windows",
                                     "top_source_share", "ok", "note")}
    rec["lift_wo_top"] = allr.get("lift_wo_top")
    rec["live_n"] = live.get("n", 0)
    rec["live_hit"] = live.get("hit")
    rec["live_lift"] = live.get("lift")
    created = created_lc(lesson)
    hold = evaluate(pred, corpus, after_lc=created) if allr.get("ok") and created is not None else {"n": 0}
    rec["holdout_after_lc"] = created
    rec["holdout_n"] = hold.get("n", 0)
    rec["holdout_lift"] = hold.get("lift")
    rec["cases"] = allr.get("cases", [])[:20]
    return rec


def created_lc(lesson) -> float | None:
    """The corpus live clock when the lesson was created (its holdout starts after it); None when unknown."""
    v = (lesson.backtest or {}).get("created_lc")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
