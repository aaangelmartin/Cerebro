"""Research the strategist does by itself before every plan (pure functions over recorded data).

    rivals(feed, leaderboard, catalog, since_ts)  -> what the leading teams buy and sell, from whom, at what price
    idle(live, me, my_offers, goals, now)         -> is our bot idle, and the likely reasons
    llm_health(live, spend, now)                  -> API errors by key/kind, dead keys, spend anomalies
    venues(venues, our_id)                        -> traffic and fees per venue, ours compared
    offer_outliers(my_offers, me, record)         -> our open offers far above value/market, or outbid
    offers_to_us(my_offers, me, allies)           -> offers addressed to us, values, last copies, page completion
    unknown_offers(my_offers, live)               -> our open offers no process of ours posted
    gap(leaderboard)                              -> our negotiating/market split against the leaders

Everything is summarised to fit a prompt. Text written by other players never appears here except
card refs and numbers.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

US = "t10"


def read_jsonl(path: Path, max_bytes: int = 3_000_000) -> list[dict]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            raw = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    if raw and max_bytes < size:
        raw = raw[1:]                      # first line may be cut
    out = []
    for ln in raw:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _book(catalog: dict) -> dict[str, dict]:
    out = {}
    rar = catalog.get("rarities") or {}
    for st in catalog.get("sets") or []:
        for c in st.get("cards") or []:
            out[c.get("id")] = {"rarity": c.get("rarity"), "book": c.get("book") or (rar.get(c.get("rarity")) or {}).get("book")}
    return out


def gap(leaderboard: dict) -> dict:
    teams = leaderboard.get("teams") or []
    us = next((t for t in teams if t.get("team") == US), {})
    if not teams:
        return {}
    lead_neg = max(teams, key=lambda t: t.get("negotiating") or 0)
    lead_mkt = max(teams, key=lambda t: t.get("market") or 0)
    lead = teams[0]
    return {"our_rank": us.get("rank"), "our_score": us.get("score"),
            "our_negotiating": us.get("negotiating"), "our_market": us.get("market"),
            "leader": {k: lead.get(k) for k in ("team", "score", "negotiating", "market")},
            "best_negotiating": {k: lead_neg.get(k) for k in ("team", "negotiating", "deals")},
            "best_market": {k: lead_mkt.get(k) for k in ("team", "market", "venue")},
            "gap_negotiating": round((lead_neg.get("negotiating") or 0) - (us.get("negotiating") or 0), 2),
            "gap_market": round((lead_mkt.get("market") or 0) - (us.get("market") or 0), 2),
            "our_deals": us.get("deals"), "median_deals": sorted(t.get("deals") or 0 for t in teams)[len(teams) // 2]}


def rivals(feed: list[dict], leaderboard: dict, catalog: dict, since_ts: float, top: int = 5) -> dict:
    """Deals (settlements) of the leading teams since `since_ts`: buys/sells with price vs book, partners."""
    teams = leaderboard.get("teams") or []
    lead = [t.get("team") for t in sorted(teams, key=lambda t: -(t.get("negotiating") or 0))[:top]]
    lead += [t.get("team") for t in teams[:3] if t.get("team") not in lead]
    if US not in lead:
        lead.append(US)
    book = _book(catalog)
    per: dict[str, dict] = {t: {"buys": [], "sells": [], "partners": {}, "messages": 0, "threads": 0,
                                 "listings": 0} for t in lead}
    for r in feed:
        if float(r.get("ts") or 0) < since_ts:
            continue
        p = r.get("payload") or {}
        typ = r.get("type")
        if typ == "settlement":
            price = p.get("price")
            parties = p.get("parties") or []
            for it in p.get("items") or []:
                ref = it.get("ref")
                b = (book.get(ref) or {}).get("book")
                row = {"ref": ref, "price": price, "book": b, "via": p.get("persona") or p.get("venue")}
                if it.get("to") in per:
                    per[it["to"]]["buys"].append({**row, "from": it.get("frm")})
                if it.get("frm") in per:
                    per[it["frm"]]["sells"].append({**row, "to": it.get("to")})
            for t in parties:
                if t in per:
                    for o in parties:
                        if o != t:
                            per[t]["partners"][o] = per[t]["partners"].get(o, 0) + 1
        elif typ == "thread.message":
            t = p.get("team")
            if t in per:
                per[t]["messages"] += 1
        elif typ == "thread.opened":
            t = p.get("team")
            if t in per:
                per[t]["threads"] += 1
        elif typ == "offer.listed":
            t = r.get("actor")
            if t in per:
                per[t]["listings"] += 1
    by_score = {t.get("team"): t for t in teams}
    out = {}
    for t, d in per.items():
        sets: dict[str, int] = {}
        for b in d["buys"]:
            s = str(b["ref"] or "").split("-")[0]
            sets[s] = sets.get(s, 0) + 1
        paid = [b["price"] for b in d["buys"] if isinstance(b.get("price"), (int, float))]
        sc = by_score.get(t) or {}
        out[t] = {"score": sc.get("score"), "negotiating": sc.get("negotiating"), "market": sc.get("market"),
                  "deals_total": sc.get("deals"), "buys": len(d["buys"]), "sells": len(d["sells"]),
                  "spent": sum(paid), "sets_bought": sets, "partners": d["partners"],
                  "dealer_messages": d["messages"], "threads_opened": d["threads"], "listings": d["listings"],
                  "messages_per_deal": round(d["messages"] / max(1, len(d["buys"]) + len(d["sells"])), 1),
                  "last_buys": d["buys"][-8:], "last_sells": d["sells"][-6:]}
    return {"since_minutes": round((time.time() - since_ts) / 60), "teams": out}


def idle(live: Path, me: dict, my_offers: list[dict], goals: dict, decisions: list[dict], outcomes: list[dict],
         status: dict) -> dict:
    """Ticks without actions lately and the likely causes."""
    ticks = [int(d.get("tick")) for d in decisions if isinstance(d.get("tick"), int)]
    cur = status.get("tick") or (max(ticks) if ticks else None)
    window = 20
    acted = {t for t in ticks if cur is not None and t > cur - window}
    idle_ticks = window - len(acted) if cur is not None else None
    cash = int(me.get("cash") or 0)
    control = {}
    try:
        control = json.loads((Path(live) / "control.json").read_text())
    except (OSError, ValueError):
        pass
    try:
        from bazaar import config as _cfg
        reserve = int(control.get("cash_reserve", _cfg.CASH_RESERVE))
    except Exception:  # noqa: BLE001
        reserve = 15
    small = int(control.get("goal_small_deal_p", 30))
    try:
        from bazaar.core.context import dealer_committed
        dealer = int(dealer_committed({"me": me, "threads": status.get("threads") or []}))
    except Exception:  # noqa: BLE001
        dealer = 0
    locked = sum(int((o.get("give") or {}).get("cash") or 0) for o in my_offers
                 if o.get("maker") == US and o.get("status", "open") == "open" and o.get("thread") is None)
    vetoes: dict[str, int] = {}
    for d in decisions:
        v = d.get("verdict") or {}
        if v.get("ok") is False:
            vetoes[v.get("rail") or "?"] = vetoes.get(v.get("rail") or "?", 0) + 1
    refused: dict[str, int] = {}
    for o in outcomes:
        if o.get("status") in ("refused", "error"):
            k = f"{o.get('kind')}: {str((o.get('response') or {}).get('message') or (o.get('response') or {}).get('error') or '')[:60]}"
            refused[k] = refused.get(k, 0) + 1
    sources: dict[str, int] = {}
    for d in decisions:
        sources[d.get("source") or "?"] = sources.get(d.get("source") or "?", 0) + 1
    causes = []
    available = cash - reserve - locked - dealer
    if locked and available < small:
        causes.append(f"{locked} P of our {cash} P is locked in open market bids: after the {reserve} P reserve "
                      f"and {dealer} P in dealer bids only {available} P is free for deals (< {small} P)")
    if goals:
        causes.append(f"saving for goal cards {goals}: other buys are limited")
    if vetoes:
        causes.append(f"rail vetoes {vetoes}")
    if refused:
        causes.append(f"game refusals {dict(list(refused.items())[:4])}")
    if sources.get("fallback", 0) > sources.get("opus", 0) + sources.get("council", 0):
        causes.append("most decisions came from code fallback, not Claude (check llm health)")
    doms = status.get("domains") or {}
    quiet = [k for k, v in doms.items() if isinstance(v, dict) and not v.get("actions")]
    return {"tick": cur, "ticks_without_actions_last_20": idle_ticks, "cash": cash, "cash_locked_in_bids": locked,
            "cash_reserve": reserve, "dealer_committed": dealer, "cash_available": available,
            "decision_sources": sources, "rail_vetoes": vetoes, "refusals": refused,
            "domains_without_actions_now": quiet, "likely_causes": causes}


def llm_health(live: Path, spend: dict, now: float | None = None, window_s: float = 1800) -> dict:
    now = now or time.time()
    rows = [r for r in read_jsonl(live / "llm.jsonl", 600_000) if now - float(r.get("ts") or 0) <= window_s]
    by: dict[str, dict] = {}
    for r in rows:
        k = r.get("key") or "?"
        b = by.setdefault(k, {"ok": 0, "errors": {}})
        if r.get("error"):
            kind = r.get("error_kind") or "error"
            b["errors"][kind] = b["errors"].get(kind, 0) + 1
            b["last_error"] = str(r.get("error"))[:120]
        elif r.get("usage") is not None or r.get("cost_usd") is not None:
            b["ok"] += 1
    keys = {k: {kk: v.get(kk) for kk in ("usd_today", "dead", "cooldown_s")} for k, v in
            (spend.get("by_key") or {}).items()}
    anomalies = []
    for k, b in by.items():
        errs = sum(b["errors"].values())
        if errs and errs >= b["ok"]:
            anomalies.append(f"key {k}: {errs} errors vs {b['ok']} ok in 30 min ({b.get('last_error', '')[:80]})")
    for k, v in keys.items():
        if v.get("dead"):
            anomalies.append(f"key {k} is dead: {str(v['dead'])[:80]}")
    usd, cap = spend.get("usd"), spend.get("cap")
    if isinstance(usd, (int, float)) and isinstance(cap, (int, float)) and cap and usd / cap > 0.8:
        anomalies.append(f"spend {usd:.1f} $ is {usd / cap:.0%} of today's cap")
    return {"calls_30min": len(rows), "by_key_30min": by, "keys": keys, "spend_today": usd,
            "by_purpose": spend.get("by_purpose"), "model_now": spend.get("model_now"), "anomalies": anomalies}


def venues(venue_list: list[dict], our_id: str | None) -> dict:
    rows = []
    for v in venue_list:
        rows.append({k: v.get(k) for k in ("venue", "owner", "fee_bps", "fee_per_card", "trades", "volume",
                                           "fees", "traders", "pairs", "value_created", "starter", "status")})
    rows.sort(key=lambda r: -(r.get("trades") or 0))
    ours = next((r for r in rows if r.get("venue") == our_id), None)
    return {"ours": ours, "busiest": rows[:6], "count": len(rows),
            "team_venues_with_trades": sum(1 for r in rows if (r.get("trades") or 0) > 0 and r.get("owner") != "world")}


def offer_outliers(my_offers: list[dict], me: dict, record: Path, limit: int = 12) -> dict:
    """Our own open offers priced far from our value or from the rest of the market (to cancel or reprice).

    sell (we give a card for cash): ask > max(2 x our value + 5, 1.5 x the cheapest other ask of that card + 3)
    bid (we give cash for a card): price >= our value of the card (paying above value loses points), or
    the bid has been open > 60 ticks while others bid more for the same card."""
    own_ids = {o.get("id") for o in my_offers if o.get("maker") == US}
    held = {a.get("id"): a for a in me.get("assets") or []}
    asks: dict[str, list[int]] = {}
    bids: dict[str, list[int]] = {}
    books = Path(record) / "books"
    try:
        files = list(books.glob("*.json"))
    except OSError:
        files = []
    for p in files:
        try:
            b = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        for o in b.get("offers") or []:
            # public books anonymise makers: drop our own offers by id too
            if o.get("maker") == US or o.get("id") in own_ids or o.get("status", "open") != "open":
                continue
            g, w = o.get("give") or {}, o.get("want") or {}
            if w.get("cash") and len(g.get("assets") or []) == 1:
                asks.setdefault(g["assets"][0].get("ref"), []).append(int(w["cash"]))
            if g.get("cash"):
                for t in w.get("types") or []:
                    if t.startswith("card:"):
                        bids.setdefault(t[5:], []).append(int(g["cash"]))
    out = []
    for o in my_offers:
        if o.get("maker") != US or o.get("status", "open") != "open" or o.get("thread") is not None:
            continue
        g, w = o.get("give") or {}, o.get("want") or {}
        if w.get("cash") and g.get("assets"):
            a = g["assets"][0]
            ref = a.get("ref")
            value = (held.get(a.get("id")) or {}).get("your_value")
            best = min(asks.get(ref) or [0]) or None
            ask = int(w["cash"])
            others = sorted(asks.get(ref) or [])
            median = others[len(others) // 2] if others else None
            limit_v = value + max(10.0, 0.9 * value) if value is not None else None
            limit_m = 1.6 * median if median else None
            if (limit_v is not None and ask > limit_v) or (limit_m is not None and ask > limit_m):
                out.append({"offer": o.get("id"), "venue": o.get("venue"), "kind": "sell", "card": ref, "ask": ask,
                            "our_value": value, "cheapest_other_ask": best,
                            "why": "ask far above our value and the market: it will not fill and holds the card"})
        elif g.get("cash"):
            refs = [t[5:] for t in w.get("types") or [] if t.startswith("card:")]
            price = int(g["cash"])
            for ref in refs:
                top = max(bids.get(ref) or [0]) or None
                if top and top > price:
                    out.append({"offer": o.get("id"), "venue": o.get("venue"), "kind": "bid", "card": ref,
                                "price": price, "best_rival_bid": top,
                                "why": "outbid by another team: the cash is parked in a bid that will not fill"})
    return {"outliers": out[:limit], "checked": len(my_offers)}


def offers_to_us(my_offers: list[dict], me: dict, allies: dict) -> list[dict]:
    """Offers other teams addressed to us, with what each side gives at our values and the page completion
    of the sets we would give from (the keep-one rule protects the last copy of LAV/MAL/RET cards)."""
    held = {a.get("id"): a for a in me.get("assets") or []}
    counts: dict[str, int] = {}
    for a in held.values():
        counts[a.get("ref")] = counts.get(a.get("ref"), 0) + 1
    pages = {p.get("set"): p for p in (me.get("album") or {}).get("pages") or []}
    out = []
    for o in my_offers:
        if o.get("to") != US or o.get("maker") == US or o.get("status", "open") != "open" or o.get("thread") is not None:
            continue
        g, w = o.get("give") or {}, o.get("want") or {}
        we_give = []
        for a in w.get("assets") or []:
            mine = held.get(a.get("id")) or {}
            we_give.append({"ref": a.get("ref"), "id": a.get("id"), "value": mine.get("your_value"),
                            "copies_held": counts.get(a.get("ref"), 0)})
        for t in w.get("types") or []:
            if t.startswith("card:"):
                ref = t[5:]
                vals = sorted((x.get("your_value") or 0) for x in held.values() if x.get("ref") == ref)
                we_give.append({"ref": ref, "value": vals[0] if vals else None, "copies_held": counts.get(ref, 0)})
        give_value = sum((x.get("value") or 0) for x in we_give) + int(w.get("cash") or 0)
        get_value = int(g.get("cash") or 0)
        sets = {str(x["ref"]).split("-")[0] for x in we_give if x.get("ref")}
        out.append({"offer": o.get("id"), "maker": o.get("maker"), "ally": o.get("maker") in allies.values(),
                    "venue": o.get("venue"), "expires_tick": o.get("expires_tick"),
                    "they_give": {"cash": g.get("cash"), "cards": [a.get("ref") for a in g.get("assets") or []]
                                  + [t[5:] for t in g.get("types") or [] if t.startswith("card:")]},
                    "we_give": we_give, "we_give_cash": w.get("cash"),
                    "value_gain_cash_only": round(get_value - give_value, 1),
                    "last_copy": any(x.get("copies_held", 0) <= 1 for x in we_give),
                    "page_completion": {st: f"{(pages.get(st) or {}).get('have')}/{(pages.get(st) or {}).get('of')}"
                                        for st in sets}})
    return out


def unknown_offers(my_offers: list[dict], live: Path) -> list[dict]:
    """Our open market offers that none of our processes posted (someone else using our key?)."""
    ours = set()
    for r in read_jsonl(Path(live) / "outcomes.jsonl", 8_000_000):
        resp = r.get("response") or {}
        if isinstance(resp, dict) and resp.get("id") is not None:
            ours.add(resp.get("id"))
        off = (r.get("realised") or {}).get("offer") if isinstance(r.get("realised"), dict) else None
        if off:
            ours.add(off)
    out = []
    for o in my_offers:
        if o.get("maker") == US and o.get("thread") is None and o.get("status", "open") == "open" and o.get("id") not in ours:
            g, w = o.get("give") or {}, o.get("want") or {}
            out.append({"offer": o.get("id"), "venue": o.get("venue"), "created_tick": o.get("created_tick"),
                        "give": [a.get("ref") for a in g.get("assets") or []] + ([f"{g['cash']} P"] if g.get("cash") else []),
                        "want": (w.get("types") or []) + ([f"{w['cash']} P"] if w.get("cash") else [])})
    return out


COMPONENTS = ("score", "negotiating", "market", "deals", "album_filled", "pages_complete")


def scoreboard(record: Path, now: float | None = None) -> dict:
    """Every team's score components now, and their change over the last 1 h and 2 h (leaderboard stream)."""
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    rows = read_jsonl(Path(record).parent / "leaderboard" / f"{day}.jsonl")
    snaps = [(float(r.get("ts") or 0), {t.get("team"): t for t in (r.get("data") or {}).get("teams") or []})
             for r in rows if (r.get("data") or {}).get("teams")]
    if not snaps:
        return {}
    cur_ts, cur = snaps[-1]

    def at(ago: float) -> dict:
        target = now - ago
        best = snaps[0]
        for ts, d in snaps:
            if ts <= target:
                best = (ts, d)
        return best[1]

    h1, h2 = at(3600), at(7200)
    teams = {}
    for tid, t in cur.items():
        row = {k: t.get(k) for k in COMPONENTS}
        keys = COMPONENTS if tid == US else ("score", "negotiating", "market", "deals")
        row = {k: row[k] for k in keys}
        for label, past in (("d1h", h1), ("d2h", h2)):
            p = past.get(tid) or {}
            row[label] = {k: round(float(t.get(k) or 0) - float(p.get(k) or 0), 2) for k in keys
                          if p.get(k) is not None and k != "deals" or (k == "deals" and p.get(k) is not None)}
        row["rank"] = t.get("rank")
        teams[tid] = row
    gainers = {}
    for k in ("score", "negotiating", "market"):
        gainers[k] = sorted(([tid, (r.get("d1h") or {}).get(k, 0)] for tid, r in teams.items()),
                            key=lambda x: -x[1])[:5]
    lead = {k: max(teams.items(), key=lambda kv: kv[1].get(k) or 0)[0] for k in ("score", "negotiating", "market")}
    return {"tick": (rows[-1].get("data") or {}).get("tick"), "weights": (rows[-1].get("data") or {}).get("weights"),
            "us_now": teams.get(US), "leaders": {k: {"team": v, **{c: teams[v].get(c) for c in COMPONENTS}}
                                                 for k, v in lead.items()},
            "top_gainers_1h": gainers, "teams": teams, "snapshots": len(snaps),
            "note": "judges (40 %) are scored outside the game; this board covers negotiation and market-making"}


def buy_impact(feed: list[dict], me: dict, since_ts: float) -> dict:
    """Our recent buys per set: what we paid against our value now, and how far each page is.
    A set whose buys add little value and whose page is far from complete is a candidate for avoid_buy_sets."""
    vals = {}
    for a in me.get("assets") or []:
        vals.setdefault(a.get("ref"), []).append(a.get("your_value") or 0)
    pages = {p.get("set"): p for p in (me.get("album") or {}).get("pages") or []}
    aff = me.get("affinity") or {}
    per: dict[str, dict] = {}
    for r in feed:
        if float(r.get("ts") or 0) < since_ts or r.get("type") != "settlement":
            continue
        p = r.get("payload") or {}
        for it in p.get("items") or []:
            if it.get("to") != US or not it.get("ref") or it.get("kind") == "pack":
                continue
            st = str(it["ref"]).split("-")[0]
            d = per.setdefault(st, {"buys": 0, "spent": 0, "value_now": 0.0})
            d["buys"] += 1
            d["spent"] += int(p.get("price") or 0)
            d["value_now"] += max(vals.get(it["ref"]) or [0])
    out = {}
    for st, d in per.items():
        pg = pages.get(st) or {}
        share = (pg.get("have") or 0) / (pg.get("of") or 10)
        surplus = d["value_now"] - d["spent"]
        out[st] = {**d, "surplus": round(surplus, 1), "surplus_per_P": round(surplus / max(1, d["spent"]), 2),
                   "page": f"{pg.get('have')}/{pg.get('of')}", "affinity": aff.get(st),
                   "low_impact": bool(share <= 0.5 and (aff.get(st) or 1) < 1.2
                                      and surplus / max(1, d["spent"]) < 0.25)}
    return out


def venue_flow(feed: list[dict], venue: str | None, since_ts: float) -> dict:
    """Listings on our venue split into addressed (to a team: invisible on the public board) and public, and the
    fills there. Public offers attract third parties and let our broker pair them (market-making score)."""
    if not venue:
        return {}
    addressed, public, fills = {}, {}, []
    for r in feed:
        if float(r.get("ts") or 0) < since_ts:
            continue
        p = r.get("payload") or {}
        if r.get("type") == "offer.listed" and p.get("venue") == venue:
            o = p.get("offer") or {}
            bucket = addressed if o.get("to") else public
            bucket[r.get("actor") or o.get("maker")] = bucket.get(r.get("actor") or o.get("maker"), 0) + 1
        elif r.get("type") == "settlement" and p.get("venue") == venue:
            fills.append({"parties": p.get("parties"), "price": p.get("price"),
                          "items": [it.get("ref") for it in p.get("items") or []]})
    return {"venue": venue, "addressed_listings_by_maker": addressed, "public_listings_by_maker": public,
            "fills": len(fills), "last_fills": fills[-6:]}


def alliances(feed: list[dict], allies: dict, our_venue: str | None, my_offers: list[dict], since_ts: float) -> dict:
    """Measured benefit of each alliance: trades the ally closed on OUR venue vs trades we closed on THEIRS, their
    listings on our venue (addressed vs public), and our open offers sitting on their venue."""
    out = {}
    for venue, team in (allies or {}).items():
        d = {"ally": team, "their_venue": venue, "their_fills_on_our_venue": 0, "our_fills_on_their_venue": 0,
             "their_listings_on_our_venue": {"addressed": 0, "public": 0},
             "our_open_offers_on_their_venue": sum(1 for o in my_offers if o.get("maker") == US
                                                   and o.get("venue") == venue and o.get("status", "open") == "open")}
        for r in feed:
            if float(r.get("ts") or 0) < since_ts:
                continue
            p = r.get("payload") or {}
            if r.get("type") == "settlement":
                parties = p.get("parties") or []
                if p.get("venue") == our_venue and team in parties:
                    d["their_fills_on_our_venue"] += 1
                if p.get("venue") == venue and US in parties:
                    d["our_fills_on_their_venue"] += 1
            elif r.get("type") == "offer.listed" and p.get("venue") == our_venue and r.get("actor") == team:
                d["their_listings_on_our_venue"]["addressed" if (p.get("offer") or {}).get("to") else "public"] += 1
        d["reciprocal"] = d["their_fills_on_our_venue"] > 0 or d["our_fills_on_their_venue"] == 0
        out[venue] = d
    return out


def broker(live: Path, now: float | None = None) -> dict:
    """Our broker and the Market Test: heartbeat (session_stats, efficiency_estimate, errors) and the refused
    matches of the latest bench run (e.g. "price must sit between the ask and the bid" = a probe bug)."""
    st = {}
    try:
        st = json.loads((Path(live) / "broker_status.json").read_text())
    except (OSError, ValueError):
        pass
    out = {k: st.get(k) for k in ("session", "mode", "rule", "writes", "has_key", "efficiency_estimate",
                                  "stall_efficiency", "session_stats", "matches_total", "errors")}
    runs = sorted((Path(live) / "bench").glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if (Path(live) / "bench").exists() else []
    refused, ok = [], 0
    for p in runs[-2:]:
        for r in read_jsonl(p, 400_000):
            for res in r.get("results") or []:
                if res.get("status") == "ok":
                    ok += 1
                elif res.get("status"):
                    refused.append({"tick": r.get("tick"), "kind": res.get("kind"), "error": res.get("error"),
                                    "message": str(res.get("message") or "")[:120], "price": res.get("price")})
    out.update(bench_runs=[p.stem for p in runs[-2:]], matches_ok=ok, refused=refused[-8:], refused_count=len(refused))
    # official result of each Market Test session vs the free stall (half the bench points = stall level,
    # full points = the mean of the top three venues)
    sessions = []
    for r in read_jsonl(Path(live) / "bench" / "results.jsonl", 200_000):
        sc = r.get("score") or {}
        sessions.append({"run": r.get("run"), "tick": r.get("tick"), "efficiency": sc.get("bench_efficiency"),
                         "bench_points": sc.get("bench_points"), "stall_efficiency": r.get("stall_efficiency"),
                         "vs_stall": round(float(sc["bench_efficiency"]) - float(r["stall_efficiency"]), 4)
                         if sc.get("bench_efficiency") is not None and r.get("stall_efficiency") is not None else None})
    out["sessions_vs_stall"] = sessions[-6:]
    return out


def _allies() -> dict:
    try:
        from bazaar.market.protocol import ALLIED_VENUES
        return dict(ALLIED_VENUES)
    except Exception:  # noqa: BLE001
        return {}


def summarise(record: Path, live: Path, me: dict, leaderboard: dict, catalog: dict, venue_list: list[dict],
              my_offers: list[dict], goals: dict, decisions: list[dict], outcomes: list[dict], status: dict,
              spend: dict, now: float | None = None, hours: float = 2.0) -> dict[str, Any]:
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    feed = read_jsonl(Path(record).parent / "feed" / f"{day}.jsonl")
    our_venue = (me.get("venue") or {}).get("venue") if isinstance(me.get("venue"), dict) else me.get("venue")
    out: dict[str, Any] = {}
    for name, fn in (("gap", lambda: gap(leaderboard)),
                     ("rivals_last_2h", lambda: rivals(feed, leaderboard, catalog, now - hours * 3600)),
                     ("our_bot", lambda: idle(live, me, my_offers, goals, decisions, outcomes, status)),
                     ("llm_health", lambda: llm_health(live, spend, now)),
                     ("venues", lambda: venues(venue_list, our_venue)),
                     ("our_offer_outliers", lambda: offer_outliers(my_offers, me, record)),
                     ("offers_to_us", lambda: offers_to_us(my_offers, me, _allies())),
                     ("offers_not_posted_by_our_bot", lambda: unknown_offers(my_offers, live)),
                     ("scoreboard", lambda: scoreboard(record, now)),
                     ("our_buys_by_set_last_3h", lambda: buy_impact(feed, me, now - 3 * 3600)),
                     ("our_venue_flow_last_2h", lambda: venue_flow(feed, our_venue, now - hours * 3600)),
                     ("broker", lambda: broker(live, now)),
                     ("alliances_today", lambda: alliances(feed, _allies(), our_venue, my_offers, now - 14 * 3600))):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 - one broken analysis must not stop the plan
            out[name] = {"error": f"{type(e).__name__}: {e}"[:160]}
    return out
