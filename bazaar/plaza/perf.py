"""What the venue earns us, for the Performance screen and the dashboard's "Market v07" section.

The game scores a venue by the value its trades create between OTHER teams (SCORING.md): not by their count, their
volume or the fee. So this page puts three things side by side and raises an alert when they disagree:

    the game's own numbers   record/latest/me.json (score.market, score.mm_points, venue.value_created, trades...)
                             and record/latest/venues.json (every venue: trades, volume, traders, pairs)
    what our feed saw        sales between two teams, per venue, from data/live/events.jsonl (feed.py)
    what the market paired   matches by state, the ones that settled on our venue, the ones we lost elsewhere

Everything is read from the recorder's files; nothing here calls the game and nothing here knows a private limit."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import deals as deals_mod, matcher

TAIL_BYTES = 600_000
SERIES_POINTS = 60
BROKER_STALE_S = 180.0
FLAT_TICKS = 60


def _json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _tail_lines(path: Path, size: int = TAIL_BYTES) -> list[dict]:
    """The last whole JSON lines of a file that only grows."""
    try:
        with Path(path).open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(0, end - size))
            chunk = f.read()
    except OSError:
        return []
    lines = chunk.split(b"\n")
    if end > size:
        lines = lines[1:]                                      # the first one is cut
    out = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _thin(rows: list[dict], n: int = SERIES_POINTS) -> list[dict]:
    if len(rows) <= n:
        return rows
    step = len(rows) / float(n)
    return [rows[min(len(rows) - 1, int(i * step))] for i in range(n - 1)] + [rows[-1]]


class Perf:
    def __init__(self, live: Path, record: Path, venue: str = matcher.VENUE, host: str = matcher.HOST,
                 clock=time.time):
        self.live, self.record, self.venue, self.host, self.clock = Path(live), Path(record), venue, host, clock
        self.cache: dict[str, tuple] = {}

    def _cached(self, name: str, path: Path, build):
        try:
            stamp = (path.stat().st_mtime, path.stat().st_size)
        except OSError:
            return []
        kept = self.cache.get(name)
        if kept and kept[0] == stamp:
            return kept[1]
        out = build(path)
        self.cache[name] = (stamp, out)
        return out

    # ---- the game's own numbers
    def me(self) -> dict:
        return _json(self.record / "latest" / "me.json", {}) or {}

    def venues(self) -> list[dict]:
        data = _json(self.record / "latest" / "venues.json", {}) or {}
        rows = data.get("venues") if isinstance(data, dict) else data
        return [v for v in rows or [] if isinstance(v, dict) and v.get("venue")]

    def value_series(self) -> list[dict]:
        """Our venue over time, as the game reports it: value created, market-maker points, trades."""
        folder = self.record / "me"
        try:
            files = sorted(folder.glob("*.jsonl"))
        except OSError:
            files = []
        if not files:
            return []

        def build(path: Path) -> list[dict]:
            rows, last = [], None
            for r in _tail_lines(path):
                d = r.get("data") if isinstance(r.get("data"), dict) else r
                v, s = d.get("venue") or {}, d.get("score") or {}
                if not isinstance(v, dict) or not isinstance(s, dict) or d.get("tick") is None:
                    continue
                row = {"tick": d.get("tick"), "value_created": v.get("value_created"), "mm_points": s.get("mm_points"),
                       "market": s.get("market"), "trades": v.get("trades"), "pairs": v.get("pairs")}
                if row != last:
                    rows.append(row)
                    last = row
            return rows
        rows = []
        for path in files[-2:]:
            rows += self._cached("me:" + path.name, path, build)
        return rows

    def market_series(self) -> list[dict]:
        """Every team's market score over time (the public leaderboard, as our bot keeps it)."""
        path = self.live / "leaderboard.jsonl"

        def build(p: Path) -> list[dict]:
            out = []
            for r in _tail_lines(p):
                teams = r.get("teams")
                if isinstance(teams, dict) and r.get("tick") is not None:
                    out.append({"tick": r["tick"], "market": {t: v.get("market") for t, v in teams.items()
                                                              if isinstance(v, dict)}})
            return out
        return self._cached("leaderboard", path, build)

    def broker(self) -> dict:
        """v07 is a board venue: two public offers that cross do nothing until our broker pairs them."""
        st = _json(self.live / "broker_status.json", None)
        if not isinstance(st, dict):
            return {"state": "off", "detail": "no status file", "updated": None, "tick": None}
        age = self.clock() - float(st.get("updated") or 0)
        return {"state": "on" if age < BROKER_STALE_S else "stale", "updated": st.get("updated"),
                "tick": st.get("tick"), "matches_total": st.get("matches_total"), "mode": st.get("mode"),
                "detail": f"last beat {int(age)} s ago" + ("" if st.get("writes", True) else " (read only)")}

    # ---- the page
    def performance(self, board, snap: dict) -> dict:
        me = self.me()
        score, venue = me.get("score") or {}, me.get("venue") or {}
        venues = self.venues()
        ours = next((v for v in venues if v.get("venue") == self.venue), {}) or venue
        feed = board.feed
        closed = list(board.deals.closed)
        settled = [c for c in closed if c["state"] == "settled"]
        lost = [c for c in closed if c["state"] == "settled_elsewhere"]
        volume = sum(int(c.get("price") or 0) for c in settled)
        funnel = board.deals.funnel()
        waits = sorted((c["tick"] - c["proposed_tick"]) for c in settled if c.get("proposed_tick") is not None)
        proposed = funnel.get("proposed") or 0
        series = self.value_series()
        by_venue = feed.by_venue()
        team_deals = sum(by_venue.values())
        conn = board.connect.overview()
        per_team: dict[str, dict] = {}
        for c in settled:
            for role, t in (("as_seller", c["seller"]), ("as_buyer", c["buyer"])):
                row = per_team.setdefault(t, {"team": t, "deals": 0, "volume": 0, "as_seller": 0, "as_buyer": 0})
                row["deals"] += 1
                row["volume"] += int(c.get("price") or 0)
                row[role] += 1
        for d in feed.team_deals:                              # every sale on our venue, paired by us or not
            if d["venue"] != self.venue:
                continue
            for t in d["parties"]:
                row = per_team.setdefault(t, {"team": t, "deals": 0, "volume": 0, "as_seller": 0, "as_buyer": 0})
                row["venue_deals"] = row.get("venue_deals", 0) + 1
        for t, row in per_team.items():
            row.setdefault("venue_deals", 0)
            row["connected"] = bool((conn.get(t) or {}).get("agent"))
        market_now = (self.market_series() or [{}])[-1].get("market") or {}
        best_other = max([v for t, v in market_now.items() if t != self.host and isinstance(v, (int, float))],
                         default=None)
        alerts = self.alerts(board, snap, venue or ours, feed, lost, series, conn)
        tick = snap.get("tick")
        return {
            "tick": tick,
            "score": {"market": score.get("market"), "mm_points": score.get("mm_points"), "rank": score.get("rank"),
                      "total": score.get("score"), "bench_points": score.get("bench_points"),
                      "bench_efficiency": score.get("bench_efficiency"), "best_other_market": best_other},
            "venue": {"venue": self.venue, "name": ours.get("name"), "trades": ours.get("trades"),
                      "volume": ours.get("volume"), "traders": ours.get("traders"), "pairs": ours.get("pairs"),
                      "fee_bps": ours.get("fee_bps"), "status": ours.get("status"),
                      "value_created": venue.get("value_created")},
            "feed": {"venue_deals": feed.counts["venue_deals"], "venue_volume": feed.counts["venue_volume"],
                     "team_deals": team_deals, "by_venue": by_venue,
                     "share": round(by_venue.get(self.venue, 0) / team_deals, 3) if team_deals else None},
            "ours": {"settled": len(settled), "volume": volume,
                     "saved_fees": sum(matcher.rastro_fee(int(c.get("price") or 0)) for c in settled),
                     "settled_elsewhere": len(lost),
                     "by_rarity": {r: sum(1 for c in settled if c.get("rarity") == r)
                                   for r in ("legendary", "epic", "rare", "uncommon", "common")}},
            "lost": [{k: c.get(k) for k in ("id", "tick", "seller", "buyer", "ref", "price", "venue", "settlement")}
                     for c in lost[-40:]][::-1],
            "alert": alerts[0]["text"] if alerts else None,
            "alerts": alerts,
            "funnel": {s: funnel.get(s, 0) for s in deals_mod.STATES},
            "now": board.deals.counts(),
            "settle": {"rate": round(len(settled) / proposed, 2) if proposed else None,
                       "median_ticks": waits[len(waits) // 2] if waits else None},
            "per_team": sorted(per_team.values(), key=lambda r: (-r["deals"], -r["venue_deals"], r["team"])),
            "per_tick": self.per_tick(settled, lost, tick),
            "per_hour": board.hours(),
            "teams": {"total": sum(1 for x in snap["sheets"].values() if not x.get("host")), "connected": sum(1 for c in conn.values() if c.get("agent")),
                      "verified": sum(1 for c in conn.values() if c.get("connected")),
                      "online": sum(1 for c in conn.values() if c.get("online"))},
            "venues": sorted(({"venue": v["venue"], "name": v.get("name"), "owner": v.get("owner"),
                               "fee_bps": v.get("fee_bps"), "trades": v.get("trades"), "volume": v.get("volume"),
                               "traders": v.get("traders"), "pairs": v.get("pairs"),
                               "market": market_now.get(v.get("owner")),
                               "ours": v["venue"] == self.venue} for v in venues),
                             key=lambda v: (not v["ours"], -(v.get("trades") or 0))),
            "series": {"value": _thin(series), "market": _thin([
                {"tick": r["tick"], "ours": r["market"].get(self.host),
                 "best_other": max([v for t, v in r["market"].items() if t != self.host
                                    and isinstance(v, (int, float))], default=None)}
                for r in self.market_series()])},
            "broker": self.broker(),
            "scoring": "the game scores the value created between other teams on v07, not the count of trades",
        }

    def per_tick(self, settled: list[dict], lost: list[dict], tick, last: int = 120) -> list[dict]:
        """Trades the market paired, by tick: closed on our venue, and closed somewhere else."""
        rows: dict[int, dict] = {}
        low = (tick or 0) - last
        for c, key in [(c, "settled") for c in settled] + [(c, "elsewhere") for c in lost]:
            if (c.get("tick") or 0) >= low:
                row = rows.setdefault(c["tick"], {"tick": c["tick"], "settled": 0, "elsewhere": 0, "volume": 0})
                row[key] += 1
                if key == "settled":
                    row["volume"] += int(c.get("price") or 0)
        return [rows[t] for t in sorted(rows)]

    def alerts(self, board, snap: dict, venue: dict, feed, lost: list[dict], series: list[dict], conn: dict) -> list[dict]:
        """What needs a decision, the most urgent first. Each one says what to do."""
        out = []
        tick = snap.get("tick") or 0
        game, seen = venue.get("trades"), feed.counts["venue_deals"]
        if isinstance(game, int) and game != seen:
            out.append({"kind": "count", "text": f"the game counts {game} trades on {self.venue}; our feed saw "
                        f"{seen}. Check the recorder for gaps before trusting the numbers below."})
        drops = [(a, b) for a, b in zip(series, series[1:])
                 if isinstance(a.get("value_created"), (int, float)) and isinstance(b.get("value_created"), (int, float))
                 and b["value_created"] < a["value_created"] - 0.05]
        if drops and (drops[-1][1].get("tick") or 0) >= tick - 240:
            a, b = drops[-1]
            out.append({"kind": "value_drop", "text": f"a trade at tick {b.get('tick')} lowered the value created "
                        f"from {a['value_created']} to {b['value_created']}: find it and tighten the gate."})
        recent = [c for c in lost if (c.get("tick") or 0) >= tick - 240]
        if recent:
            c = recent[-1]
            out.append({"kind": "lost", "text": f"{len(recent)} matched trade(s) closed off {self.venue} (last: "
                        f"{c['seller']} -> {c['buyer']} {c['ref']} on {c.get('venue')}): tell those agents to close on "
                        f"{self.venue}."})
        b = self.broker()
        if b["state"] != "on":
            out.append({"kind": "broker", "text": f"the broker is {b['state']}: public offers that cross on "
                        f"{self.venue} are not being paired. Restart it through the supervisor."})
        if not any(c.get("agent") for c in conn.values()):
            out.append({"kind": "no_agents", "text": "no team has connected an agent: nothing can be matched. "
                        "Ask the teams in person."})
        vals = [r for r in series if isinstance(r.get("value_created"), (int, float))]
        if vals and tick and len(vals) > 1:
            last_change = next((b.get("tick") for a, b in reversed(list(zip(vals, vals[1:])))
                                if a["value_created"] != b["value_created"]), None)
            share = feed.by_venue(tick - FLAT_TICKS)
            away = sum(n for v, n in share.items() if v != self.venue)
            if away and (last_change is None or tick - (last_change or 0) > FLAT_TICKS):
                out.append({"kind": "flat", "text": f"no value created for {FLAT_TICKS} ticks while teams closed "
                            f"{away} trade(s) on other venues: announce, and talk to teams."})
        return out

    def stats(self, board, snap: dict, name: str) -> dict:
        """The public counters of the landing page: only what is true and already public in the game."""
        fees = snap.get("fees") or {}
        f = fees.get(self.venue) or {"bps": 0, "per_card": 0}
        r = fees.get("rastro") or {"bps": 500, "per_card": 1}
        conn = board.connect.overview()
        st = snap.get("stats") or {}
        now = board.deals.counts()
        return {"venue": self.venue, "name": name, "fee_bps": f.get("bps", 0), "per_card": f.get("per_card", 0),
                "rastro": {"fee_bps": r.get("bps", 500), "per_card": r.get("per_card", 1)},
                "deals": st.get("deals", 0), "volume": st.get("volume", 0), "saved_fees": st.get("saved_fees", 0),
                "last_deal_tick": st.get("last_deal_tick"),
                "traders": len({t for d in board.feed.team_deals if d["venue"] == self.venue for t in d["parties"]}),
                "teams": sum(1 for s in snap["sheets"].values() if not s.get("host")),
                "teams_connected": sum(1 for c in conn.values() if c.get("agent")),
                "agents_online": sum(1 for c in conn.values() if c.get("online")),
                "matches_live": sum(now[s] for s in deals_mod.LIVE_STATES),
                "matches_settled": int(board.deals.funnel().get("settled", 0)), "tick": snap.get("tick")}
