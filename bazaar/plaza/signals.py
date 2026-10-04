"""Hidden demand and hidden supply: what only this market knows, told to one team about its own cards.

For a card a team holds: are there connected agents whose private `max` is well over the best public bid on any
venue? For a card it wants: agents whose private `min` is well under the best public ask? The answer is a coarse
level and a coarse count, never a number and never a name, and it is built so that nobody's limit can be read:

- at least K other teams must be over the mark, or nothing is said (one team and no team look the same);
- two levels only (`some`, `strong`) and two counts only ("2-3", "4+");
- an answer stands for HOLD ticks for that team and card, whatever anybody changes meanwhile;
- it never depends on the asking team's own limits, and the public bid or ask it compares with is the best one
  posted by OTHER teams, so the asker cannot move the mark itself;
- only for cards the team says it holds (demand) or wants (supply); the host and banned teams are out.

Kept in memory only: nothing of this is written under data/live, logged, or shown to another team or to our panel
(which gets one global count)."""
from __future__ import annotations

import hashlib
import threading

K_MIN = 2                       # teams over the mark before anything is said
SOME, STRONG = 1.10, 1.30       # a private max this far over the public bid (a min this far under the ask)
HOLD = 60                       # ticks an answer stands, the same window as a match answer
MAX_CARDS = 60                  # cards of one team looked at
API = "/plaza/api/me/signals"


def bucket(n: int) -> str:
    return "2-3" if n <= 3 else "4+"


def level(marks: list[float], base: float, above: bool) -> tuple[str | None, int]:
    """(level, how many teams are at it). `marks` are the other teams' private numbers."""
    for name, f in (("strong", STRONG), ("some", SOME)):
        n = sum(1 for m in marks if (m >= base * f if above else m <= base / f))
        if n >= K_MIN:
            return name, n
    return None, 0


class Signals:
    def __init__(self):
        self.lock = threading.Lock()
        self.held: dict[tuple, tuple[int, dict | None]] = {}    # (team, side, ref) -> (until tick, the answer)
        self.acked: dict[str, set] = {}

    def _base(self, snap: dict, team: str, ref: str, side: str) -> tuple[int | None, str]:
        """The public mark: the best bid (ask) other teams have open; else the card's last price or list price."""
        prices = [o["price"] for o in snap.get("offers") or [] if o.get("ref") == ref and not o.get("to")
                  and o.get("side") == side and o.get("maker") != team and o.get("price")]
        if prices:
            return (max(prices) if side == "bid" else min(prices)), "public"
        row = next((c for c in (snap.get("board") or {}).get("cards") or [] if c["ref"] == ref), None) or {}
        ref_price = row.get("median") or row.get("book")
        return (int(ref_price) if ref_price else None), "reference"

    def _others(self, board, snap: dict, team: str, ref: str, lists: tuple, field: str) -> list[float]:
        out = []
        banned = board.strikes.banned_teams()
        for other, sheet in (snap.get("sheets") or {}).items():
            if other == team or sheet.get("host") or other in banned or not sheet.get("verified"):
                continue
            if not any(e.get("ref") == ref and e.get("source") == "agent" for k in lists for e in sheet.get(k) or []):
                continue
            mark = (board.vault.get(other).get(ref) or {}).get(field)
            if isinstance(mark, (int, float)) and not isinstance(mark, bool) and mark > 0:
                out.append(float(mark))
        return out

    def _one(self, board, snap: dict, team: str, ref: str, side: str, tick: int) -> dict | None:
        key = (team, side, ref)
        held = self.held.get(key)
        if held and tick < held[0]:
            return held[1]
        sell = side == "sell"
        base, basis = self._base(snap, team, ref, "bid" if sell else "ask")
        answer = None
        if base:
            marks = self._others(board, snap, team, ref, ("wants",) if sell else ("spares", "for_sale"),
                                 "max" if sell else "min")
            lvl, n = level(marks, base, above=sell)
            if lvl:
                answer = {"ref": ref, "level": lvl, "teams": bucket(n), "basis": basis,
                          ("best_public_bid" if sell else "best_public_ask"): base if basis == "public" else None,
                          "reference_price": base if basis == "reference" else None}
        self.held[key] = (tick + HOLD, answer)
        return answer

    def view(self, board, snap: dict, team: str, owned: set, wants: set) -> dict:
        tick = int(snap.get("tick") or 0)
        cat = snap.get("cat") or {}
        with self.lock:
            sell = [s for s in (self._one(board, snap, team, r, "sell", tick) for r in sorted(owned & set(cat))[:MAX_CARDS]) if s]
            buy = [s for s in (self._one(board, snap, team, r, "buy", tick)
                               for r in sorted((wants - owned) & set(cat))[:MAX_CARDS]) if s]
            until = min((u for (t, _, _), (u, _) in self.held.items() if t == team), default=tick + HOLD)
            for old in [k for k, (u, _) in self.held.items() if u < tick - HOLD]:
                self.held.pop(old, None)
        def act(ref: str, lst: str, field: str) -> dict:
            return {"target": "plaza", "method": "POST", "auth": "X-Plaza-Token", "path": "/plaza/api/me/cards",
                    "body": {"op": "add", "list": lst, "ref": ref, field: f"<your {field}>"}}
        return {"team": team, "tick": tick, "next_refresh_tick": until,
                "sell": [{**s, **board.card(s["ref"], snap), "action": act(s["ref"], "spares", "min")} for s in sell],
                "buy": [{**s, **board.card(s["ref"], snap), "action": act(s["ref"], "wants", "max")} for s in buy],
                "note": "levels and counts are coarse on purpose: no price and no team is ever named"}

    def count(self) -> int:
        with self.lock:
            return sum(1 for _, a in self.held.values() if a)

    @staticmethod
    def _id(team: str, side: str, ref: str, until: int) -> str:
        return "a-" + hashlib.sha1(f"signal|{team}|{side}|{ref}|{until}".encode()).hexdigest()[:12]

    def actions(self, view: dict) -> list[dict]:
        team, out = view["team"], []
        done = self.acked.get(team) or set()
        for side, rows, words in (("sell", view["sell"], "would pay more than the best public bid for"),
                                  ("buy", view["buy"], "would sell under the best public ask")):
            for s in rows:
                aid = self._id(team, side, s["ref"], view["next_refresh_tick"])
                if aid in done:
                    continue
                out.append({"id": aid, "type": "signal", "side": side, "card": s["ref"], "level": s["level"],
                            "teams": s["teams"],
                            "why": f"{s['teams']} connected agents {words} {s['ref']} ({s['level']}). To trade it on "
                                   f"v07, list it with your own limit: the price is set inside both limits. "
                                   "Informative: act or not, and acknowledge it.",
                            "request": {"target": "plaza", "method": "GET", "auth": "X-Plaza-Token", "path": API,
                                        "body": None}, "list_it": s["action"]})
        return out

    def ack(self, team: str, aid) -> None:
        if isinstance(aid, str) and aid.startswith("a-"):
            row = self.acked.setdefault(team, set())
            row.add(aid)
            if len(row) > 2000:
                row.clear()


def attach(board) -> None:
    board.signals = Signals()


def _signals(board) -> Signals:
    if getattr(board, "signals", None) is None:
        attach(board)
    return board.signals


def for_team(board, snap: dict, team: str) -> dict:
    from . import deals_api
    sheet = (snap.get("sheets") or {}).get(team) or {}
    wants = {e["ref"] for e in sheet.get("wants") or []}
    return _signals(board).view(board, snap, team, deals_api._owned(board, team, snap), wants)


def get(h, path: str, q: dict, snap: dict) -> bool:
    if path != API:
        return False
    h.route = "me"
    team = h.me_team(q)                                        # a proved team that is not banned, or it raises
    h._json(200, for_team(h.board, snap, team))                # never with open CORS: it is the team's own
    return True


def write(h, method: str, path: str, body) -> bool:
    return False
