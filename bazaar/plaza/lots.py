"""Auctions: a team puts one card it holds up as a lot, other teams bid in public, and the card stays with the
seller until the best bid is accepted. An awarded lot is a match like any other: the winner posts the addressed
offer on v07, the seller accepts it in the game, and only the game's feed settles it.

    open -> ended -> awarded -> settled          (or unsold, cancelled, settled_elsewhere)

Bids, their teams and their amounts are public by design. A lot's reserve (the least its seller takes) is as
private as a limit: it lives sealed beside the vault and is in no answer and in no file under data/live. A bid is
a commitment: a winner that does not post its offer within POST_TICKS loses the lot to the next bid and takes a
strike of the market's rule. The host never sells, bids or awards; our panel can only cancel a lot."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from . import matcher, safe
from .private import seal, unseal
from .store import MAX_PRICE, REF_RX, PlazaError, write_atomic

VENUE = matcher.VENUE
LIVE = ("open", "ended", "awarded")
DONE = ("settled", "settled_elsewhere", "unsold", "cancelled")
MOVES = {"open": {"ended", "awarded", "unsold", "cancelled"}, "ended": {"awarded", "unsold", "cancelled"},
         "awarded": {"settled", "settled_elsewhere", "ended", "cancelled"},
         "settled": set(), "settled_elsewhere": set(), "unsold": set(), "cancelled": set()}
TICKS, MIN_TICKS, MAX_TICKS = 40, 4, 240     # how long a lot runs
SNIPE_TICKS, MAX_EXTENSIONS = 4, 3           # a bid this close to the end moves the end, this many times
ACCEPT_TICKS = 40                            # an ended lot waits this long for its seller
POST_TICKS = 12                              # the winner posts its offer on the venue within this
LOTS_PER_TEAM, TOP_BIDS_PER_TEAM, MAX_BIDS = 5, 8, 60
KEEP_DONE = 200
RECENT = 30
ID_RX = re.compile(r"l-[0-9a-f]{8}")
LOT_PATH = re.compile(r"/plaza/api/lot/(l-[0-9a-f]{8})")
LOT_ACT = re.compile(r"/plaza/api/lot/(l-[0-9a-f]{8})/(bid|accept|cancel)")
TOKEN_HEADER = "X-Plaza-Token"
PUBLIC_NOTE = "bids are public: every team sees who bid and how much"


def step(price: int) -> int:
    """The least a bid adds to the one before it: 1 P under 20, 5 P from there."""
    return 1 if price < 20 else 5


def whole(value, name: str, low: int = 1, high: int = MAX_PRICE) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value != int(value) \
            or not low <= value <= high:
        raise PlazaError(400, "bad_request", f"{name} is a whole number from {low} to {high}")
    return int(value)


def keys(body, allowed: set, need: set = frozenset()) -> dict:
    if not isinstance(body, dict):
        raise PlazaError(400, "bad_request", "send a JSON object")
    unknown = set(body) - allowed
    if unknown:
        raise PlazaError(400, "bad_request", f"unknown key {', '.join(sorted(map(str, unknown)))[:60]}; allowed: "
                         + (", ".join(sorted(allowed)) or "none"))
    if not need <= set(body):
        raise PlazaError(400, "bad_request", "send " + ", ".join(sorted(need)))
    return body


class Lots:
    def __init__(self, path: Path | str, private_dir: Path | str, key: bytes, host: str = "t10", clock=time.time):
        self.path, self.host, self.clock, self.key = Path(path), host, clock, key
        self.secret = Path(private_dir) / "lots.bin"
        self.lock = threading.RLock()
        data = safe.load(self.path)
        self.lots: dict[str, dict] = data.get("lots") if isinstance(data.get("lots"), dict) else {}
        self.seen: dict[str, list] = data.get("seen") if isinstance(data.get("seen"), dict) else {}
        self.reserves: dict[str, int] = self._load_reserves()
        self.tick = 0

    # ---- files
    def _load_reserves(self) -> dict:
        for path in (self.secret, self.secret.with_name(self.secret.name + ".bak")):
            try:
                data = json.loads(unseal(self.key, path.read_bytes()).decode("utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return {k: int(v) for k, v in data.items() if isinstance(v, int)}
        return {}

    def _save(self, secret: bool = False) -> None:
        safe.save(self.path, {"lots": self.lots, "seen": self.seen})
        if secret:
            try:
                if self.secret.exists():
                    self.secret.with_name(self.secret.name + ".bak").write_bytes(self.secret.read_bytes())
            except OSError:
                pass
            write_atomic(self.secret, seal(self.key, json.dumps(self.reserves).encode("utf-8")), 0o600)

    # ---- helpers
    def _move(self, lot: dict, state: str, tick: int, **extra) -> bool:
        if state not in MOVES.get(lot["state"], ()):
            return False
        lot.update(state=state, state_tick=tick, **extra)
        lot.setdefault("history", []).append({"state": state, "tick": tick})
        return True

    @staticmethod
    def best(lot: dict) -> dict | None:
        live = [b for b in lot["bids"] if b["state"] == "live"]
        return max(live, key=lambda b: (b["price"], -b["n"])) if live else None

    def get(self, lot_id) -> dict:
        lot = self.lots.get(lot_id) if isinstance(lot_id, str) and ID_RX.fullmatch(lot_id) else None
        if lot is None:
            raise PlazaError(404, "not_found", "no such lot")
        return lot

    def view(self, lot: dict, wanted: dict | None = None, viewer: str | None = None) -> dict:
        """What anybody reads of a lot. The reserve is never here; its seller is told only that it set one."""
        best = self.best(lot)
        left = max(0, lot["ends_tick"] - self.tick) if lot["state"] == "open" else 0
        out = {k: lot.get(k) for k in ("id", "seller", "ref", "name", "rarity", "start", "state", "state_tick",
                                       "opened_tick", "ends_tick", "extensions", "winner", "price", "match", "history")}
        out.update(best_bid=best["price"] if best else None, best_bidder=best["team"] if best else None,
                   next_bid=(best["price"] + step(best["price"])) if best else lot["start"], ticks_left=left,
                   bids=[{k: b[k] for k in ("n", "team", "price", "tick", "state")} for b in lot["bids"]],
                   bid_count=len(lot["bids"]), venue=VENUE, note=PUBLIC_NOTE,
                   wanted_by=(wanted or {}).get(lot["ref"], 0))
        if viewer and viewer == lot["seller"]:
            out["you"] = {"role": "seller", "reserve_set": lot["id"] in self.reserves,
                          "reserve": self.reserves.get(lot["id"])}
        elif viewer and any(b["team"] == viewer for b in lot["bids"]):
            mine = max((b for b in lot["bids"] if b["team"] == viewer), key=lambda b: b["price"])
            out["you"] = {"role": "bidder", "bid": mine["price"], "state": mine["state"],
                          "winning": bool(best and best["team"] == viewer)}
        return out

    def listing(self, wanted: dict | None = None, viewer: str | None = None) -> dict:
        with self.lock:
            rows = sorted(self.lots.values(), key=lambda x: (x["state"] not in LIVE, x["ends_tick"] if x["state"] == "open"
                                                             else -x.get("state_tick", 0), x["id"]))
            live = [self.view(x, wanted, viewer) for x in rows if x["state"] in LIVE]
            done = [self.view(x, wanted, viewer) for x in rows if x["state"] in DONE][:RECENT]
            return {"tick": self.tick, "venue": VENUE, "lots": live, "recent": done, "rules": {
                "default_ticks": TICKS, "max_ticks": MAX_TICKS, "snipe_ticks": SNIPE_TICKS, "post_ticks": POST_TICKS,
                "accept_ticks": ACCEPT_TICKS, "step": "1 P under 20, 5 P from 20", "bids": "public"}}

    # ---- a team's moves
    def create(self, team: str, body, card: dict | None, owned: set, tick: int) -> dict:
        body = keys(body, {"card", "start", "reserve", "ticks"}, {"card"})
        ref = body["card"]
        if not isinstance(ref, str) or not REF_RX.fullmatch(ref) or card is None:
            raise PlazaError(400, "bad_request", "card is a card of the catalog, such as LAV-09")
        if team == self.host:
            raise PlazaError(403, "host", "the host never sells or bids here")
        if ref not in owned:
            raise PlazaError(400, "not_yours", f"your sheet does not say you hold {ref}: list it as a spare, a card "
                                               "for sale or in `have` first")
        floor = matcher.FLOOR.get(card.get("rarity") or "", 1)
        start = whole(body.get("start", floor), "start", floor)
        reserve = whole(body["reserve"], "reserve", start) if body.get("reserve") is not None else None
        ticks = whole(body.get("ticks", TICKS), "ticks", MIN_TICKS, MAX_TICKS)
        with self.lock:
            mine = [x for x in self.lots.values() if x["seller"] == team and x["state"] in LIVE]
            same = next((x for x in mine if x["ref"] == ref), None)
            if same:
                return {**self.view(same, viewer=team), "repeated": True}       # one lot per card and team
            if len(mine) >= LOTS_PER_TEAM:
                raise PlazaError(429, "slow_down", f"a team runs at most {LOTS_PER_TEAM} lots at a time")
            n = self.seen.setdefault("made", [0])
            n[0] += 1
            lot_id = "l-" + hashlib.sha1(f"{team}|{ref}|{tick}|{n[0]}".encode()).hexdigest()[:8]
            lot = {"id": lot_id, "seller": team, "ref": ref, "name": card.get("name") or ref,
                   "rarity": card.get("rarity"), "start": start, "state": "open", "state_tick": tick,
                   "opened_tick": tick, "ends_tick": tick + ticks, "extensions": 0, "bids": [], "winner": None,
                   "price": None, "match": None, "award_tick": None, "history": [{"state": "open", "tick": tick}]}
            self.lots[lot_id] = lot
            if reserve is not None:
                self.reserves[lot_id] = reserve
            self._save(secret=reserve is not None)
            return self.view(lot, viewer=team)

    def bid(self, team: str, lot_id: str, body, tick: int, banned=frozenset()) -> dict:
        body = keys(body, {"price"}, {"price"})
        price = whole(body["price"], "price")
        with self.lock:
            lot = self.get(lot_id)
            if team == self.host:
                raise PlazaError(403, "host", "the host never sells or bids here")
            if team == lot["seller"]:
                raise PlazaError(403, "own_lot", "a team does not bid on its own lot")
            if lot["state"] != "open" or tick >= lot["ends_tick"]:
                raise PlazaError(409, "closed", f"this lot is {lot['state'] if lot['state'] != 'open' else 'over'}")
            best = self.best(lot)
            if best and best["team"] == team and best["price"] == price:
                return {**self.view(lot, viewer=team), "repeated": True}        # the same bid twice changes nothing
            least = best["price"] + step(best["price"]) if best else lot["start"]
            if price < least:
                raise PlazaError(409, "too_low", f"the next bid is at least {least} P")
            if len(lot["bids"]) >= MAX_BIDS:
                raise PlazaError(409, "closed", "this lot took all the bids it can")
            top = sum(1 for x in self.lots.values() if x["state"] in ("open", "ended") and x["id"] != lot_id
                      and (self.best(x) or {}).get("team") == team)
            if top >= TOP_BIDS_PER_TEAM:
                raise PlazaError(429, "slow_down", f"a team leads at most {TOP_BIDS_PER_TEAM} lots at a time")
            for b in lot["bids"]:
                if b["state"] == "live":
                    b["state"] = "outbid"
            lot["bids"].append({"n": len(lot["bids"]) + 1, "team": team, "price": price, "tick": tick, "state": "live"})
            if lot["ends_tick"] - tick <= SNIPE_TICKS and lot["extensions"] < MAX_EXTENSIONS:
                lot["ends_tick"] += SNIPE_TICKS                 # a late bid gives the others time to answer
                lot["extensions"] += 1
            self._save()
            return self.view(lot, viewer=team)

    def accept(self, team: str, lot_id: str, tick: int, award) -> dict:
        """The seller takes the best bid now, whether the lot is still running or over."""
        with self.lock:
            lot = self.get(lot_id)
            if team != lot["seller"]:
                raise PlazaError(403, "not_a_party", "only the seller accepts a bid")
            if lot["state"] == "awarded":
                return {**self.view(lot, viewer=team), "repeated": True}
            if lot["state"] not in ("open", "ended"):
                raise PlazaError(409, "closed", f"this lot is {lot['state']}")
            if not self.best(lot):
                raise PlazaError(409, "no_bids", "there is no bid to accept")
            self._award(lot, tick, award)
            self._save()
            return self.view(lot, viewer=team)

    def cancel(self, team: str | None, lot_id: str, tick: int, expire=None) -> dict:
        """The seller, while nobody bid or no bid reached its reserve. `team` None is our panel: any lot, any time."""
        with self.lock:
            lot = self.get(lot_id)
            if team is not None and team != lot["seller"]:
                raise PlazaError(403, "not_a_party", "only the seller cancels its lot")
            if lot["state"] == "cancelled":
                return {**self.view(lot, viewer=team), "repeated": True}
            if lot["state"] in DONE:
                raise PlazaError(409, "closed", f"this lot is {lot['state']}")
            best = self.best(lot)
            reserve = self.reserves.get(lot["id"])
            if team is not None and (lot["state"] == "awarded" or (best and (reserve is None or best["price"] >= reserve))):
                raise PlazaError(409, "has_bids", "a lot with a bid at or over its reserve is not withdrawn: accept it "
                                                  "or let it run")
            if lot["state"] == "awarded" and lot.get("match") and expire:
                expire(lot["match"])
            self._move(lot, "cancelled", tick, by="seller" if team else "host")
            self.reserves.pop(lot["id"], None)
            self._save(secret=True)
            return self.view(lot, viewer=team)

    # ---- awarding and what follows
    def _award(self, lot: dict, tick: int, award) -> None:
        best = self.best(lot)
        match = award(lot, best)                               # the match the two agents now follow
        self._move(lot, "awarded", tick, winner=best["team"], price=best["price"], match=match, award_tick=tick)

    def sync(self, tick: int, award, match_of, expire, default, auto=lambda team: True) -> list[dict]:
        """Moves every lot on: closes the ones that ran out, awards what its seller already agreed to, follows the
        awarded ones through their match. `match_of(id)` is the match record or None; `default(lot, bid)` is told
        when a winner did not honour its bid. Returns what happened, for the floor and the teams' records."""
        out: list[dict] = []
        with self.lock:
            self.tick = max(self.tick, int(tick or 0))
            tick, changed = self.tick, False
            for lot in list(self.lots.values()):
                before = (lot["state"], lot.get("winner"))
                if lot["state"] == "open" and tick >= lot["ends_tick"]:
                    self._move(lot, "ended" if self.best(lot) else "unsold", tick)
                if lot["state"] == "ended":
                    best, reserve = self.best(lot), self.reserves.get(lot["id"])
                    if not best:
                        self._move(lot, "unsold", tick)
                    elif reserve is not None and best["price"] >= reserve and auto(lot["seller"]):
                        self._award(lot, tick, award)          # its seller named this price beforehand
                    elif tick - lot["state_tick"] > ACCEPT_TICKS:
                        self._move(lot, "unsold", tick)
                elif lot["state"] == "awarded":
                    rec = match_of(lot["match"]) or {}
                    state = rec.get("state")
                    if state in ("settled", "settled_elsewhere"):
                        self._move(lot, state, tick, price=rec.get("price") or lot["price"])
                        self.reserves.pop(lot["id"], None)
                    else:
                        passed = next((m.get("team") for m in rec.get("messages") or [] if m.get("action") == "pass"), None)
                        late = state in (None, "proposed") and tick - (lot.get("award_tick") or tick) > POST_TICKS \
                            and not rec.get("reported_offer")
                        if late or state in ("passed", "expired", None):
                            broke = lot["winner"] if (late or passed == lot["winner"]) and passed != lot["seller"] else None
                            for b in lot["bids"]:
                                if b["state"] == "live":
                                    b["state"] = "defaulted" if broke else "void"
                            if state in ("proposed", "offer_on_v07", "accepted"):
                                expire(lot["match"])
                            if broke:
                                default(lot, {"team": broke, "price": lot["price"], "match": lot["match"]})
                            nxt = max((b for b in lot["bids"] if b["state"] == "outbid"
                                       and b["team"] not in {x["team"] for x in lot["bids"] if x["state"] == "defaulted"}),
                                      key=lambda b: b["price"], default=None)
                            if nxt:
                                nxt["state"] = "live"          # the next best bid stands again
                            self._move(lot, "ended", tick, winner=None, price=None, match=None, award_tick=None)
                if (lot["state"], lot.get("winner")) != before:
                    changed = True
                    out.append({"lot": lot["id"], "state": lot["state"], "seller": lot["seller"], "ref": lot["ref"],
                                "winner": lot.get("winner"), "price": lot.get("price"), "tick": tick,
                                "match": lot.get("match")})
            done = sorted((x for x in self.lots.values() if x["state"] in DONE), key=lambda x: x.get("state_tick", 0))
            for x in done[:max(0, len(done) - KEEP_DONE)]:
                self.lots.pop(x["id"], None)
                self.reserves.pop(x["id"], None)
                changed = True
            if changed:
                self._save(secret=True)
        return out

    # ---- for the agents' queue
    def actions(self, team: str, wants: set) -> list[dict]:
        """One informative action per open lot of a card the team wants, until it acknowledges it."""
        with self.lock:
            told = set(self.seen.get(team) or [])
            out = []
            for lot in self.lots.values():
                if lot["state"] != "open" or lot["seller"] == team or lot["ref"] not in wants:
                    continue
                aid = "a-" + hashlib.sha1(f"auction|{team}|{lot['id']}".encode()).hexdigest()[:12]
                if aid in told:
                    continue
                best = self.best(lot)
                nxt = best["price"] + step(best["price"]) if best else lot["start"]
                out.append({"id": aid, "type": "auction", "lot": lot["id"], "card": lot["ref"],
                            "why": f"{lot['ref']}, a card you want, is up for auction until tick {lot['ends_tick']}: "
                                   f"the next bid is {nxt} P. Bid only what you would pay: a winning bid is a "
                                   "commitment. Ignore it if you do not want it; acknowledge it either way.",
                            "request": {"target": "plaza", "method": "GET", "auth": "X-Plaza-Token",
                                        "path": f"/plaza/api/lot/{lot['id']}", "body": None},
                            "bid": {"target": "plaza", "method": "POST", "auth": "X-Plaza-Token",
                                    "path": f"/plaza/api/lot/{lot['id']}/bid", "body": {"price": nxt}},
                            "next_bid": nxt, "ends_tick": lot["ends_tick"]})
            return out

    def ack(self, team: str, aid) -> bool:
        if not isinstance(aid, str) or not aid.startswith("a-"):
            return False
        with self.lock:
            for lot in self.lots.values():
                if aid == "a-" + hashlib.sha1(f"auction|{team}|{lot['id']}".encode()).hexdigest()[:12]:
                    row = self.seen.setdefault(team, [])
                    if aid not in row:
                        row.append(aid)
                        del row[:-400]
                        self._save()
                    return True
        return False


# ---- the board's side: awarding is a match, a default is a strike
def attach(board) -> None:
    board.lots = Lots(board.live / "plaza_lots.json", board.vault.folder, board.vault.key, board.host)


def _lots(board) -> Lots:
    if getattr(board, "lots", None) is None:
        attach(board)
    return board.lots


def _award(board):
    def award(lot: dict, bid: dict) -> str:
        price = bid["price"]
        m = {"kind": "sale", "seller": lot["seller"], "buyer": bid["team"], "ref": lot["ref"], "name": lot["name"],
             "rarity": lot["rarity"], "price": price, "basis": "auction", "saves": matcher.rastro_fee(price),
             "last_of_page": False, "priority": 0, "confidence": "auction", "score": 99.0, "auction": lot["id"],
             "why": f"auction {lot['id']}: {bid['team']} won {lot['ref']} at {price} P and {lot['seller']} accepted"}
        m["id"] = matcher.match_id(m)
        rec = board.deals.force(m)
        with board.deals.lock:                                 # both gave their word: the bid, and taking it
            rec["agreed"] = [lot["seller"], bid["team"]]
            board.deals._save()
        return m["id"]
    return award


def _default(board):
    def default(lot: dict, bid: dict) -> None:
        try:
            board.strikes.record(f"lot|{lot['id']}|{bid['team']}", match=bid.get("match") or lot["id"], ref=lot["ref"],
                                 venue="no venue: its winning bid in an auction was not honoured", tick=board.lots.tick,
                                 parties=[lot["seller"], bid["team"]], maker=bid["team"],
                                 verified={lot["seller"], bid["team"]}, saw={lot["seller"], bid["team"]})
        except Exception:  # noqa: BLE001 - the rule never stops an auction
            pass
    return default


def _expire(board):
    def expire(mid: str) -> None:
        try:
            board.deals.expire(mid)
        except PlazaError:
            pass
    return expire


def _auto(board):
    def auto(team: str) -> bool:
        try:
            return board.queue.settings(team).get("default_mode", "auto") == "auto"
        except Exception:  # noqa: BLE001
            return True
    return auto


def sync(board, tick) -> list[dict]:
    """Called with every rebuild, after the matches were brought up to date with the game."""
    lots = _lots(board)

    def match_of(mid):
        return board.deals.matches.get(mid) if mid else None
    events = lots.sync(int(tick or 0), _award(board), match_of, _expire(board), _default(board), _auto(board))
    from . import deals_api
    words = {"ended": "ended: its seller decides", "awarded": "awarded: the winner posts the offer on v07",
             "settled": "settled on v07", "settled_elsewhere": "closed on another venue", "unsold": "ended unsold",
             "cancelled": "cancelled"}
    for e in events:
        for team in {e["seller"], e.get("winner")} - {None}:
            deals_api.note(board, team, "auction", f"lot {e['lot']} ({e['ref']}): {words.get(e['state'], e['state'])}",
                           ref=e["ref"], tick=e.get("tick"))
    return events


def _wanted(snap: dict) -> dict:
    return {c["ref"]: len(c.get("seekers") or []) for c in (snap.get("board") or {}).get("cards") or []}


def _viewer(h, q: dict) -> str | None:
    from . import deals_api
    return deals_api._team_or_none(h, q)


def get(h, path: str, q: dict, snap: dict) -> bool:
    lots = _lots(h.board)
    if path == "/plaza/api/lots":
        viewer = _viewer(h, q)
        h._json(200, lots.listing(_wanted(snap), viewer), cors=viewer is None)
        return True
    m = LOT_PATH.fullmatch(path)
    if m:
        viewer = _viewer(h, q)
        with lots.lock:
            h._json(200, {**lots.view(lots.get(m.group(1)), _wanted(snap), viewer), "tick": lots.tick},
                    cors=viewer is None)
        return True
    return False


def write(h, method: str, path: str, body) -> bool:
    if method != "POST":
        return False
    act = LOT_ACT.fullmatch(path)
    if path != "/plaza/api/lots" and not act:
        return False
    board = h.board
    lots = _lots(board)
    h.route = "lot_write"
    team = h.me_team()                                         # a proved team that is not banned, or it raises
    snap = board.get()
    tick = board.now_tick(snap.get("tick")) or snap.get("tick") or 0
    with lots.lock:
        lots.tick = max(lots.tick, int(tick))
    if not act:
        from . import deals_api
        ref = body.get("card") if isinstance(body, dict) else None
        card = snap["cat"].get(ref) if isinstance(ref, str) else None
        out = lots.create(team, body, card, deals_api._owned(board, team, snap), lots.tick)
        status = 200 if out.get("repeated") else 201
    else:
        lot_id, what = act.group(1), act.group(2)
        status = 200
        if what == "bid":
            out = lots.bid(team, lot_id, body, lots.tick)
        elif what == "accept":
            keys(body if body is not None else {}, set())
            out = lots.accept(team, lot_id, lots.tick, _award(board))
        else:
            keys(body if body is not None else {}, set())
            out = lots.cancel(team, lot_id, lots.tick, _expire(board))
    board.store.touch(team)
    board.stale()
    h._json(status, {**out, "tick": lots.tick})
    return True
