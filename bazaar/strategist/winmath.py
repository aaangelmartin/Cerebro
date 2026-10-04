"""Win math for el cerebro: how far the leader is, the pace we need, and what each action is worth.

Code computes it so the plan cannot under-aim:

- per component (negotiating, market): our score, the leader's, the gap, the hours left today and tomorrow,
  and the pace per hour needed to pass the leader by today's close;
- the raw components the game gives us in /api/me (neg_points, duel_points, ladder_points, bench_points,
  mm_points) with an empirical conversion into leaderboard points (how many leaderboard points we gained per
  raw unit in the recorded hours);
- an action menu ranked by expected leaderboard points, with the cash each action needs.

Everything here is read-only and defensive: a missing file or field gives a smaller report, never an error.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

US = "t10"
RAW = {"negotiating": ("neg_points", "duel_points", "ladder_points"), "market": ("bench_points", "mm_points")}
# used only while the recorded data cannot tell (no isolated change of that raw component yet)
DEFAULT_CONV = {"neg_points": 0.05, "duel_points": 0.65, "ladder_points": 10.0, "bench_points": 6.0, "mm_points": 1.0}
MENU_PER_COMPONENT = 6
MIN_POINTS = 0.05               # menu actions below this are noise
EST_CAPTURE = 0.6               # a decent negotiated dealer deal captures about this share of the range
RESERVE_P = 5


def _f(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _rows(path: Path, max_bytes: int = 4_000_000) -> list[dict]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in data.splitlines()[1 if size > max_bytes else 0:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def score_points(record: Path, now: float | None = None) -> list[dict]:
    """Distinct snapshots of our score row today: {ts, tick, negotiating, market, <raw components>}."""
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    out, seen = [], None
    for r in _rows(Path(record).parent / "me" / f"{day}.jsonl"):
        s = (r.get("data") or {}).get("score")
        if not isinstance(s, dict):
            continue
        row = {k: _f(s.get(k)) for k in ("negotiating", "market", *RAW["negotiating"], *RAW["market"])}
        key = tuple(row.values())
        if key == seen or row["negotiating"] is None:
            continue
        seen = key
        out.append({"ts": float(r.get("ts") or 0), "tick": r.get("tick"), **row})
    return out


RESET_MIN_RAW = 3.0             # a round restart: the raw components had at least this much...
RESET_SHARE = 0.25              # ...and fell to this share of it or less between two snapshots
# t_hours runs on the wall clock while the game runs: a 60 s tick moved it 1/60 h on Friday (tick 158 -> 2.6333,
# 159 -> 2.65) and a 30 s tick 1/120 h on Saturday, so a game hour is 60 real minutes at any tick length and
# Sunday's 15 s ticks are 240 to the hour (h16.65 -> h22.65 is 09:00 -> 15:00).
GAME_HOUR_S = 3600.0


def _raw_total(p: dict) -> float:
    return sum(float(p.get(r) or 0.0) for rs in RAW.values() for r in rs)


def round_points(points: list[dict]) -> tuple[list[dict], dict | None]:
    """The snapshots of the round in play, and where it started.

    Each round scores on its own: the raw components (neg_points, duel_points, ...) go back to 0 when a round
    starts (Saturday's opening took neg_points from 68.7 to 0). Snapshots from before the last such fall belong to
    an earlier round and must not feed the conversions or the menu."""
    start = None
    cut = 0
    for i in range(1, len(points)):
        a, b = _raw_total(points[i - 1]), _raw_total(points[i])
        if a >= RESET_MIN_RAW and b <= a * RESET_SHARE:
            cut = i
            start = {"tick": points[i].get("tick"), "ts": points[i].get("ts"), "raw_before": round(a, 2),
                     "raw_after": round(b, 2)}
    return points[cut:], start


def round_info(clock: dict, schedule: dict, leaderboard: dict, reset: dict | None = None,
               now: float | None = None) -> dict:
    """The round in play: its number, name and weight, the rounds already closed, when the next one starts (game
    hours) and how long this one still runs. Rounds are averaged by weight, so each scores from zero."""
    t = _f((clock or {}).get("t_hours"))
    rounds = [r for r in (leaderboard or {}).get("rounds") or [] if isinstance(r, dict)]
    no = (clock or {}).get("round") or (leaderboard or {}).get("round")
    cur = next((r for r in rounds if r.get("round") == no), {})
    out: dict[str, Any] = {
        "round": no, "name": (clock or {}).get("round_name") or cur.get("name"), "weight": cur.get("weight"),
        "closed_rounds": [{"round": r.get("round"), "name": r.get("name"), "weight": r.get("weight")}
                          for r in rounds if r.get("status") == "closed"],
    }
    ends = []
    for u in (schedule or {}).get("upcoming") or []:
        if not isinstance(u, dict) or u.get("action") not in ("round", "end_round"):
            continue
        at = _f(u.get("at_hours"))
        if at is not None and (t is None or at >= t):
            ends.append((at, u))
    if ends:
        at, u = min(ends, key=lambda x: x[0])
        out["ends_at_hours"] = round(at, 3)
        if t is not None:
            out["hours_left_in_round"] = round(max(0.0, at - t), 2)
        if u.get("action") == "round":
            par = u.get("params") or {}
            out["next_round"] = {"at_hours": round(at, 3), "name": par.get("name"), "weight": par.get("weight")}
    ts = _f((clock or {}).get("tick_seconds"))
    if ts:
        out["tick_seconds"] = ts
        out["game_hour_real_minutes"] = round(GAME_HOUR_S / 60.0, 1)
        out["ticks_per_game_hour"] = round(GAME_HOUR_S / ts)
    if reset:
        out["started"] = reset
        if now is not None and reset.get("ts"):
            out["started_minutes_ago"] = round(max(0.0, now - float(reset["ts"])) / 60.0, 1)
    out["note"] = ("The final score averages the rounds by weight: every round starts from zero and counts on its "
                   "own. Raw components and the conversions below are this round's only; points, ladder slots and "
                   "deals from an earlier round do not carry over.")
    return out


def conversions(points: list[dict]) -> dict[str, dict]:
    """Leaderboard points per raw unit, from the recorded day.

    The leaderboard refreshes every few ticks while the raw components move every tick, so the day is cut at
    each leaderboard change; a segment where exactly one raw component of that leaderboard component moved gives
    a ratio for it. The estimate is the median ratio; with no such segment yet, a default marked as a guess."""
    out: dict[str, dict] = {}
    for comp, raws in RAW.items():
        cuts = [points[0]] if points else []
        for p in points[1:]:
            if p.get(comp) != cuts[-1].get(comp):
                cuts.append(p)
        ratios: dict[str, list[float]] = {r: [] for r in raws}
        for a, b in zip(cuts, cuts[1:]):
            d_comp = (b.get(comp) or 0) - (a.get(comp) or 0)
            moved = [(r, (b.get(r) or 0) - (a.get(r) or 0)) for r in raws]
            moved = [(r, d) for r, d in moved if abs(d) > 1e-9]
            if len(moved) == 1 and moved[0][1] > 0 and d_comp > 0:
                ratios[moved[0][0]].append(d_comp / moved[0][1])
        for r in raws:
            xs = sorted(ratios[r])
            if xs:
                out[r] = {"points_per_unit": round(xs[len(xs) // 2], 3), "samples": len(xs), "basis": "measured"}
            else:
                out[r] = {"points_per_unit": DEFAULT_CONV[r], "samples": 0, "basis": "guess"}
    return out


def _hours(clock: dict, schedule: dict, now: float) -> tuple[float | None, float | None]:
    """(game hours left today, game hours of play tomorrow)."""
    t = _f(clock.get("t_hours"))
    ups = [u for u in schedule.get("upcoming") or [] if isinstance(u, dict)]
    closes = sorted(_f(u.get("at_hours")) for u in ups if u.get("action") == "day_closes" and _f(u.get("at_hours")) is not None)
    left = tomorrow = None
    if t is not None and closes:
        nxt = [c for c in closes if c >= t]
        if nxt:
            left = round(nxt[0] - t, 2)
            if len(nxt) > 1:
                tomorrow = round(nxt[1] - nxt[0], 2)
    if left is None and clock.get("closes"):
        try:
            import datetime as _dt
            left = round(max(0.0, (_dt.datetime.fromisoformat(clock["closes"]).timestamp() - now) / 3600), 2)
        except (ValueError, TypeError):
            left = None
    if tomorrow is None:
        try:
            import datetime as _dt
            days = clock.get("days") or []
            idx = next(i for i, d in enumerate(days) if d.get("day") == clock.get("today"))
            d = days[idx + 1]
            tomorrow = round((_dt.datetime.fromisoformat(d["closes"]).timestamp()
                              - _dt.datetime.fromisoformat(d["opens"]).timestamp()) / 3600, 2)
        except (StopIteration, IndexError, KeyError, ValueError, TypeError):
            tomorrow = None
    return left, tomorrow


def components(leaderboard: dict, scoreboard: dict, hours_left: float | None) -> dict:
    teams = leaderboard.get("teams") or []
    us = next((t for t in teams if t.get("team") == US), {})
    board = (scoreboard or {}).get("teams") or {}
    out = {}
    for comp in ("score", "negotiating", "market"):
        ours = _f(us.get(comp)) or 0.0
        rivals = [t for t in teams if t.get("team") != US]
        lead = max(rivals, key=lambda t: _f(t.get(comp)) or 0.0, default={})
        lead_v = _f(lead.get(comp)) or 0.0
        gap = round(lead_v - ours, 2)
        lead_pace = max(0.0, _f(((board.get(lead.get("team")) or {}).get("d1h") or {}).get(comp)) or 0.0)
        our_pace = _f(((board.get(US) or {}).get("d1h") or {}).get(comp))
        if gap <= 0 or not hours_left:
            need = 0.0 if gap <= 0 else None
        else:                                   # close the gap by the close, while the leader keeps its own pace
            need = round(gap / hours_left + lead_pace, 2)
        row = {"now": round(ours, 2), "leader": lead.get("team"), "leader_score": round(lead_v, 2), "gap": gap,
               "leader_gain_last_hour": round(lead_pace, 2), "our_gain_last_hour": our_pace,
               "required_per_hour": need}
        if need is not None:
            row["min_target_next_hour"] = round(ours if gap <= 0 else min(lead_v, ours + need), 2)
            row["behind_pace"] = bool(gap > 0 and (our_pace is None or our_pace < need))
        out[comp] = row
    return out


def _duel_sessions(record: Path) -> dict:
    """Our duels by session: closed, deals, and the last session id."""
    out: dict[int, dict] = {}
    try:
        files = list((Path(record) / "duels").glob("*.json")) if (Path(record) / "duels").is_dir() \
            else list((Path(record).parent / "duels").glob("*.json"))
    except OSError:
        files = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("session") is None:
            continue
        s = out.setdefault(int(d["session"]), {"duels": 0, "closed": 0, "deals": 0})
        s["duels"] += 1
        if d.get("status") in ("deal", "no_deal"):
            s["closed"] += 1
            s["deals"] += d.get("status") == "deal"
    return out


def action_menu(*, cash: float, conv: dict, needs: dict | None, goals: dict | None, sets: dict | None,
                ladder: dict | None, schedule: dict | None, clock: dict | None, points: list[dict],
                duel_sessions: dict | None, our_venue: str | None, venue_growth: dict | None,
                hours_left: float | None, avoid: set[str] | None = None) -> dict[str, list[dict]]:
    """Actions ranked by expected leaderboard points, per component. Each: id, action, expected_points, cash,
    feasible (cash on hand covers it), how (the plan field that executes it)."""
    spendable = max(0.0, float(cash or 0) - RESERVE_P)
    k = {r: (conv.get(r) or {}).get("points_per_unit") or DEFAULT_CONV[r] for r in DEFAULT_CONV}
    neg: list[dict] = []
    mkt: list[dict] = []
    avoid = avoid or set()
    seen_offers, seen_swaps = set(), set()
    for o in (needs or {}).get("opportunities") or []:
        kind, gain = o.get("kind"), _f(o.get("gain")) or 0.0
        if gain <= 0 or (our_venue and o.get("venue") == our_venue):
            continue                                            # we cannot trade on our own venue
        if kind == "buy_below_value":
            ref = str(o.get("ref") or "")
            if ref[:3] in avoid or o.get("offer") in seen_offers:
                continue
            seen_offers.add(o.get("offer"))
            cost = _f(o.get("cost")) or _f(o.get("price")) or 0.0
            neg.append({"action": f"Accept offer {o.get('offer')}: buy {ref} from {o.get('team')} at {o.get('price')} P "
                                  f"({cost:g} with the fee), worth {o.get('our_value')} to us: +{gain:g} P",
                        "expected_points": gain * k["neg_points"], "cash": round(cost, 1), "how": "accept_offers",
                        "offer": o.get("offer"), "raw": {"neg_points": round(gain, 1)}})
        elif kind == "sell_to_bid":
            if o.get("offer") in seen_offers:
                continue
            seen_offers.add(o.get("offer"))
            neg.append({"action": f"Accept bid {o.get('offer')}: sell {o.get('ref')} to {o.get('team')} at "
                                  f"{o.get('price')} P, worth {o.get('our_value')} to us: +{gain:g} P",
                        "expected_points": gain * k["neg_points"], "cash": 0, "how": "accept_offers",
                        "offer": o.get("offer"), "raw": {"neg_points": round(gain, 1)}})
        elif kind in ("swap", "rival_wants_our_spare"):
            give, get = o.get("give") or o.get("ref"), o.get("get")
            if (get and str(get)[:3] in avoid) or (give, o.get("team")) in seen_swaps:
                continue
            seen_swaps.add((give, o.get("team")))
            what = f"swap {give} for {get}" if get else f"sell spare {give}"
            neg.append({"action": f"Post to {o.get('team')}: {what}: +{gain:g} P", "expected_points": gain * k["neg_points"],
                        "cash": 0, "how": "post_offers", "raw": {"neg_points": round(gain, 1)}})
    # ladder slots: an empty slot scores zero; a negotiated deal fills it with the share of the range we capture
    for lvl, row in ((ladder or {}).get("levels") or {}).items():
        empty = int(row.get("empty_slots") or 0)
        open_dealers = [d.get("id") for d in row.get("dealers") or [] if d.get("open_to_us")]
        worth = _f(row.get("slot_worth_ladder_points")) or 0.0
        if empty and open_dealers and worth:
            raw = round(empty * worth * EST_CAPTURE, 3)
            neg.append({"action": f"Fill {empty} empty level-{lvl} ladder slot(s) with {', '.join(open_dealers)}: "
                                  f"negotiated deals, buys below value or sells of spares above value "
                                  f"(each slot ~{worth * EST_CAPTURE:.3f} ladder points)",
                        "expected_points": raw * k["ladder_points"], "cash": 0, "how": "guidance.dealers",
                        "raw": {"ladder_points": raw}})
    # goal buys: the page card through a dealer is a ladder slot; through a team it is already listed above
    values = {m.get("ref"): _f(m.get("value_to_us")) for s in (sets or {}).values() for m in (s.get("missing") or [])
              if isinstance(m, dict)}
    for ref, cap in (goals or {}).items():
        v = values.get(ref)
        if not cap or v is None or any(ref in a["action"] for a in neg if a["how"] == "accept_offers"):
            continue
        neg.append({"action": f"Goal {ref} (worth {v:g}) from a dealer at {cap} P or less: page progress and a "
                              f"higher-level ladder slot", "expected_points": 0.044 * EST_CAPTURE * k["ladder_points"],
                    "cash": float(cap), "how": "goal_buys", "raw": {"ladder_points": round(0.044 * EST_CAPTURE, 3)}})
    # sessions ahead today
    t = _f((clock or {}).get("t_hours"))
    ups = [u for u in (schedule or {}).get("upcoming") or [] if isinstance(u, dict) and _f(u.get("at_hours")) is not None]
    horizon = (t + hours_left) if (t is not None and hours_left is not None) else None
    today = [u for u in ups if horizon is None or u["at_hours"] <= horizon + 1e-6]
    ds = duel_sessions or {}
    last = ds.get(max(ds)) if ds else None
    duel_gain = None
    if points and last and last.get("closed"):
        first = next((p.get("duel_points") for p in points if p.get("duel_points") is not None), None)
        cur = points[-1].get("duel_points")
        if first is not None and cur is not None and cur > first:
            duel_gain = (cur - first) / last["closed"]            # raw duel points per closed duel today
    for u in today:
        if u.get("action") != "duels":
            continue
        p = u.get("params") or {}
        rounds = int(p.get("rounds") or 1)
        n = (last or {}).get("duels") or 30
        raw = (duel_gain if duel_gain is not None else 0.25) * n * rounds
        neg.append({"action": f"{p.get('name') or 'Duels'} at h{u['at_hours']:g}: about {n * rounds} duels, answer all, "
                              f"open with a price the rival can take, close in 0-3 rounds",
                    "expected_points": raw * k["duel_points"], "cash": 0, "how": "guidance.duels",
                    "raw": {"duel_points": round(raw, 2)}, "at_hours": u["at_hours"],
                    "next_hour": bool(t is not None and u["at_hours"] - t <= 1.0)})
    benches = [u for u in today if u.get("action") == "bench"]
    if benches:
        mkt.append({"action": f"{len(benches)} Market Test(s) left today (next at h{benches[0]['at_hours']:g}): keep "
                              f"v07 open and the broker matching inside the spread",
                    "expected_points": 0.0, "cash": 0, "how": "guidance.broker",
                    "note": "holds the bench half of the market score; a missed session counts 0"})
    g = venue_growth or {}
    ours_v = g.get("ours") if isinstance(g.get("ours"), dict) else {}
    fills = _f(ours_v.get("fills_today")) or _f(ours_v.get("trades")) or 0.0
    mm_now = points[-1].get("mm_points") if points else None
    per_fill = (mm_now / fills) if (mm_now and fills) else 1.0
    pairs = len(g.get("crossing_pairs_elsewhere") or g.get("pairs") or [])
    if our_venue:
        mkt.append({"action": f"Bring other teams' crossing offers to {our_venue} ({pairs} pair(s) seen): in-game "
                              f"announcement with the card, both prices and the offer ids; each fill between two "
                              f"other teams adds about {per_fill:.2f} mm_points",
                    "expected_points": (min(pairs, 3) or 0.25) * per_fill * k["mm_points"], "cash": 0,
                    "how": "venue_announcement", "raw": {"mm_points": round((min(pairs, 3) or 0.25) * per_fill, 2)}})
    out = {}
    for comp, items in (("negotiating", neg), ("market", mkt)):
        for a in items:
            a["expected_points"] = round(float(a["expected_points"]), 2)
            a.setdefault("next_hour", True)                     # False: a session later today, not this hour's target
            a["feasible"] = (a.get("cash") or 0) <= spendable
            if not a["feasible"]:
                a["cash_short"] = round((a.get("cash") or 0) - spendable, 1)
        items.sort(key=lambda a: (-a["feasible"], -a["expected_points"]))
        keep = [a for a in items if a["expected_points"] >= MIN_POINTS or a.get("note")][:MENU_PER_COMPONENT]
        prefix = "N" if comp == "negotiating" else "M"
        for i, a in enumerate(keep, 1):
            a["id"] = f"{prefix}{i}"
        out[comp] = keep
    return out


def build(*, record: Path, me: dict, leaderboard: dict, clock: dict, schedule: dict, scoreboard: dict | None = None,
          needs: dict | None = None, goals: dict | None = None, sets: dict | None = None, ladder: dict | None = None,
          venue_growth: dict | None = None, avoid: set[str] | None = None, now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    left, tomorrow = _hours(clock or {}, schedule or {}, now)
    pts, reset = round_points(score_points(record, now))
    rnd = round_info(clock or {}, schedule or {}, leaderboard or {}, reset, now)
    # the pace is to the end of the ROUND when the schedule shows one (it may end before or after today's close)
    pace_hours = rnd.get("hours_left_in_round") if rnd.get("hours_left_in_round") else left
    conv = conversions(pts)
    comps = components(leaderboard or {}, scoreboard or {}, pace_hours)
    our_venue = (me.get("venue") or {}).get("venue") if isinstance(me.get("venue"), dict) else me.get("venue")
    menu = action_menu(cash=_f(me.get("cash")) or 0.0, conv=conv, needs=needs, goals=goals, sets=sets, ladder=ladder,
                       schedule=schedule, clock=clock, points=pts, duel_sessions=_duel_sessions(Path(record).parent),
                       our_venue=our_venue, venue_growth=venue_growth, hours_left=left, avoid=avoid)
    score = me.get("score") if isinstance(me.get("score"), dict) else {}
    for comp in ("negotiating", "market"):
        feas = [a for a in menu.get(comp) or [] if a.get("feasible") and a.get("next_hour")]
        comps.setdefault(comp, {})["menu_points_available_next_hour"] = round(sum(a["expected_points"] for a in feas), 2)
    return {
        "mission": "pass the leader in total score by today's close" if not rnd.get("hours_left_in_round")
                   else "lead this round when it ends (rounds are averaged by weight; each starts from zero)",
        "hours_left_today": left, "hours_tomorrow": tomorrow, "round": rnd,
        "components": comps,
        "raw_components_now": {r: score.get(r) for rs in RAW.values() for r in rs},
        "leaderboard_points_per_raw_unit": conv,
        "action_menu": menu,
        "behind_pace": bool((comps.get("score") or {}).get("behind_pace")),
        "how_to_use": "Every points_plan target must reach min_target_next_hour, or state the binding `constraint` "
                      "with numbers and still use every feasible menu action (cite its id, e.g. [N2]).",
    }
