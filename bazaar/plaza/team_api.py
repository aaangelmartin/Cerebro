"""The team's own routes (CONTRACT.md, 1.2): its status, its cards and private limits, its settings, what its
agent did, and the suggestion box. Called by server.py: each function answers and returns True, or returns False
and the server goes on to its own routes.

"me" is the team, whoever asks: the agent with its token or the human with its browser session. What a human
changes is an override: it wins over the agent's sheet and survives it until it is released. Private limits and
the list of cards a team holds are answered here and nowhere else."""
from __future__ import annotations

import re
import threading
import time

from . import activity as activity_mod, connect as connect_mod, matcher, private, status as status_mod, \
    suggest as suggest_mod
from .store import LISTS, MAX_HAVE, MAX_REFS, REF_RX, PlazaError, clean_refs, whole

API = "/plaza/api"
TOKEN_HEADER = "X-Plaza-Token"
TEAM_PATH = re.compile(API + r"/team/(t\d{2})")
ME_CARD_PATH = re.compile(API + r"/me/card/([A-Z]{3}-\d{2})")
PRIVATE = "only your team sees your limits"
READS_PER_MIN, WRITES_PER_MIN = 1500, 150         # per team: far above an agent and a few open pages
CARD_KEYS = {"op", "list", "ref", "price", "bid", "min", "max", "value"}
LIMITS_OF = {"wants": ("max", "value"), "spares": ("min", "value"), "for_sale": ("min", "value"), "have": ()}


class Limiter:
    """Requests a minute per team: a sliding window in memory."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.hits, self.lock = clock, {}, threading.Lock()

    def take(self, team: str, kind: str) -> None:
        limit = WRITES_PER_MIN if kind == "write" else READS_PER_MIN
        now = self.clock()
        with self.lock:
            q = [t for t in self.hits.get((team, kind), []) if now - t < 60.0]
            ok = len(q) < limit
            if ok:
                q.append(now)
            self.hits[(team, kind)] = q
        if not ok:
            raise PlazaError(429, "slow_down", "too many requests for this team; try again in a few seconds")


def attach(board) -> None:
    """Called when the board is made: the team's stores hang on it (`board.team_activity`, `board.suggest`)."""
    _wire(board)


def _wire(board):
    """The market's activity log, suggestion box and limiter, made once per board."""
    log = activity_mod.of(board)
    if getattr(board, "team_limiter", None) is None:
        with _MAKE:
            if getattr(board, "team_limiter", None) is None:
                suggest_mod.of(board)
                board.connect.listen(lambda team, kind, text: log.add(team, kind, text, tick=board.snap.get("tick")))
                board.team_limiter = Limiter()
    return log


_MAKE = threading.Lock()


def _by(h) -> str:
    return "agent" if h.headers.get(TOKEN_HEADER) else "human"


def _obj(body, keys: set, need_one: bool = True) -> dict:
    if not isinstance(body, dict):
        raise PlazaError(400, "bad_request", "send a JSON object")
    unknown = set(body) - keys
    if unknown or (need_one and not body):
        raise PlazaError(400, "bad_request", "send any of: " + ", ".join(sorted(keys)))
    return body


def _known(board, refs) -> None:
    """Every ref is a card of the catalog (when the catalog can be read at all)."""
    cat = board.get()["cat"]
    if cat and any(r not in cat for r in refs):
        raise PlazaError(400, "bad_request", "no such card: " + ", ".join(sorted(r for r in refs if r not in cat))[:80])


# ---- views
def owned(board, team: str, sheet: dict) -> list[str]:
    """The cards the team holds: what it said it has (else its duplicates and cards for sale), as corrected by hand."""
    eff = sheet["effective"]
    out = list(board.vault.have(team) or [])
    for ref in list(eff.get("spares") or []) + [e["ref"] for e in eff.get("for_sale") or []]:
        if ref not in out:
            out.append(ref)
    for ref, op in board.vault.have_overrides(team).items():
        if op == "add" and ref not in out:
            out.append(ref)
        elif op == "remove":
            out = [r for r in out if r != ref]
    return out


def cards_view(board, team: str, snap: dict) -> dict:
    sheet = board.store.sheet(team)
    eff, over = sheet["effective"], sheet["overrides"]
    limits = board.vault.get(team)
    held, by_hand = owned(board, team, sheet), board.vault.have_overrides(team)
    spares = list(eff.get("spares") or [])
    sale = {e["ref"]: e for e in eff.get("for_sale") or []}
    wants = list(eff.get("wants") or [])
    human = lambda ref, *lists: any(ref in over[x] for x in lists) or ref in by_hand or ref in over["limits"]   # noqa: E731
    have = []
    for ref in held:
        row = {**board.card(ref, snap), "owned": True,
               "as": "for_sale" if ref in sale else "duplicate" if ref in spares else "keep"}
        if sale.get(ref, {}).get("price"):
            row["price"] = sale[ref]["price"]
        have.append({**row, "by": "human" if human(ref, "spares", "for_sale") else "agent",
                     "limits": dict(limits.get(ref) or {})})
    looking = {"wants": [{"ref": r} for r in wants]}
    want = []
    for ref in wants:
        row = {**board.card(ref, snap), "owned": ref in held}
        bid = (over["wants"].get(ref) or {}).get("bid") or sheet["bids"].get(ref)
        if bid:
            row["bid"] = bid
        want.append({**row, "finishes_page": matcher.last_of_page(looking, ref),
                     "by": "human" if ref in over["wants"] or ref in over["limits"] else "agent",
                     "limits": dict(limits.get(ref) or {})})
    counts = {"have": len(have), "duplicates": len(spares), "for_sale": len(sale), "want": len(want),
              "limits_set": len([1 for v in limits.values() if v]),
              "overrides": sum(len(over[x]) for x in LISTS) + len(by_hand) + len(over["limits"])}
    return {"team": team, "tick": snap.get("tick"), "have": have, "want": want, "counts": counts,
            "declared_at": eff.get("updated"), "private": PRIVATE}


def settings_view(board, team: str) -> dict:
    q = board.queue.settings(team)
    return {"team": team, "default_mode": q["default_mode"], **board.store.settings(team), "modes": q["modes"],
            "orders": q["orders"]}


def _listed(board, team: str) -> bool:
    eff = board.store.sheet(team)["effective"]
    return any(eff.get(k) for k in LISTS)


def me_view(h, team: str, q: dict, snap: dict) -> dict:
    board = h.board
    st = board.connect.agent_status(team, _listed(board, team)) if h.headers.get(TOKEN_HEADER) else h._status(q)
    cards = cards_view(board, team, snap)
    trades = {s: 0 for s in ("proposed", "offer_on_v07", "accepted", "settled", "passed", "expired")}
    for m in board.deals.all():
        if team in (m.get("seller"), m.get("buyer")) or team in [x.get("from") for x in m.get("legs") or []]:
            if m.get("state") in trades:
                trades[m["state"]] += 1
    name = (snap.get("sheets", {}).get(team) or {}).get("name") or f"Team {int(team[1:])}"
    out = {"team": team, "name": name, "tick": snap.get("tick"), "venue": matcher.VENUE, "status": st,
           "settings": settings_view(board, team), "agent": board.queue.settings(team),
           "limits": board.vault.get(team), "owned": [c["ref"] for c in cards["have"]], "counts": cards["counts"],
           "trades": trades, "activity_seq": activity_mod.of(board).seq_of(team), "read_only": False}
    if team in snap.get("sheets", {}):                         # the public sheet, as the first page drew it
        out["home"] = {**board.team_view(team, snap), "matches": board.matches_view(snap, team)["matches"]}
    return out


# ---- reads
def get(h, path: str, q: dict, snap: dict) -> bool:
    if not path.startswith(API + "/"):
        return False
    board = h.board
    log = _wire(board)
    if path == API + "/status":
        team = board.connect.team_of(session=h._session(q), token=h.headers.get(TOKEN_HEADER))
        admin = board.store.admin()
        h._json(200, status_mod.status(board.record, matcher.VENUE, board.enabled(), admin["mm_paused"], team,
                                       board.connect.online(team) if team else None), cors=team is None)
        return True
    if path == API + "/me" and h.headers.get(TOKEN_HEADER):
        team, verified = h._agent(need_proof=False)
        if not verified:                                        # nothing of the team before its proof in the game
            h.route = "me"
            h._json(200, {"team": team, "verified": False, "read_only": True, "tick": snap.get("tick"),
                          "venue": matcher.VENUE, "status": board.connect.agent_status(team, False),
                          "next": connect_mod.PROVE_FIRST})
            return True
    elif path == API + "/agent/cards":
        team, _ = h._agent()
    elif path in (API + "/me", API + "/me/cards", API + "/me/settings", API + "/me/activity", API + "/me/suggestions"):
        team = h.me_team(q)
    else:
        return False
    board.team_limiter.take(team, "read")
    h.route = "me"
    if path == API + "/me":
        h._json(200, me_view(h, team, q, snap))
    elif path == API + "/me/cards":
        h._json(200, cards_view(board, team, snap))
    elif path == API + "/agent/cards":                          # the same, plus the two lists the first agents read
        view = board.team_view(team, snap) if team in snap.get("sheets", {}) else {}
        h._json(200, {**cards_view(board, team, snap), "limits": board.vault.get(team),
                      "available": view.get("available", []), "wanted": view.get("wanted", [])})
    elif path == API + "/me/settings":
        h._json(200, settings_view(board, team))
    elif path == API + "/me/activity":
        h._json(200, log.since(team, q.get("since", 0), q.get("limit", 100)))
    else:
        h._json(200, {"suggestions": suggest_mod.of(board).mine(team)})
    return True


# ---- writes
def write(h, method: str, path: str, body) -> bool:
    if not path.startswith(API + "/"):
        return False
    board = h.board
    log = _wire(board)
    tick = board.snap.get("tick")
    m = TEAM_PATH.fullmatch(path)
    if method == "PUT" and m:
        h.route = "declare"
        return _declare(h, m.group(1), body, log, tick)
    if method != "POST":
        return False
    m = ME_CARD_PATH.fullmatch(path)
    if not (m or path in (API + "/me/cards", API + "/me/settings", API + "/suggestions")):
        return False
    h.route = "me_write"
    team, by = h.me_team(), _by(h)
    board.team_limiter.take(team, "write")
    if m:
        ref = m.group(1)
        if ref not in board.get()["cat"]:
            raise PlazaError(404, "not_found", "no such card")
        fields = private.limits(_obj(body, set(private.FIELDS)), private.FIELDS)
        _put_limits(board, team, ref, fields, by)
        log.add(team, "limits", f"changed the private limits of {ref}", by=by, ref=ref, tick=tick)
        board.stale()
        h._json(200, {"team": team, "ref": ref, "limits": board.vault.get(team).get(ref, {}), "private": PRIVATE})
    elif path == API + "/me/cards":
        _edit(board, team, _obj(body, CARD_KEYS), by, log, tick)
        board.stale()
        h._json(200, cards_view(board, team, board.get()))
    elif path == API + "/me/settings":
        body = _obj(body, {"default_mode", "lang", "paused"})
        if any(body[k] is None for k in body):
            raise PlazaError(400, "bad_request", "default_mode is auto or ask_me; lang is en or es; paused is true or false")
        if "lang" in body or "paused" in body:
            board.store.set_settings(team, body.get("lang"), body.get("paused"))
        if "default_mode" in body:
            board.queue.set_mode(team, body["default_mode"])
        log.add(team, "settings", "changed its settings: " + ", ".join(sorted(body)), by=by, tick=tick)
        board.stale()
        h._json(200, {**settings_view(board, team), "agent": board.queue.settings(team)})
    else:
        body = _obj(body, {"text", "topic"})
        out = suggest_mod.of(board).add(team, body.get("text"), body.get("topic"), tick)
        log.add(team, "suggestion", "sent a suggestion to the host", by=by, tick=tick)
        h._json(200, out)
    return True


def _mine(board, team: str, ref: str, fields: dict, by: str) -> dict:
    """The fields this caller may write: what the human set stays the human's until it is released."""
    if by == "human":
        return fields
    locked = board.store.sheet(team)["overrides"]["limits"].get(ref) or []
    return {k: v for k, v in fields.items() if k not in locked}


def _put_limits(board, team: str, ref: str, fields: dict, by: str) -> None:
    """Stores a card's private limits."""
    fields = _mine(board, team, ref, fields, by)
    if not fields:
        return
    board.vault.put(team, ref, fields, board.snap.get("tick"))
    if by == "human":
        board.store.lock_limits(team, ref, list(fields))


def _edit(board, team: str, body: dict, by: str, log, tick) -> None:
    op, lst, ref = body.get("op"), body.get("list"), body.get("ref")
    if op not in ("add", "remove", "release") or lst not in LIMITS_OF or not isinstance(ref, str) \
            or not REF_RX.fullmatch(ref):
        raise PlazaError(400, "bad_request", "op is add, remove or release; list is wants, spares, for_sale or have; "
                                             "ref looks like LAV-03")
    _known(board, [ref])
    price = whole(body["price"], "price") if body.get("price") is not None else None
    bid = whole(body["bid"], "bid") if body.get("bid") is not None else None
    fields = private.limits({k: body[k] for k in private.FIELDS if k in body}, private.FIELDS)
    if (price is not None and lst != "for_sale") or (bid is not None and lst != "wants") \
            or set(fields) - set(LIMITS_OF[lst]):
        raise PlazaError(400, "bad_request", "price goes with for_sale, bid and max with wants, min with spares "
                                             "and for_sale, value with any of the three")
    if op != "add" and (price is not None or bid is not None or fields):
        raise PlazaError(400, "bad_request", "only add takes a price, a bid or limits")
    human = by == "human"
    if board.vault.cooling(team, ref, _mine(board, team, ref, fields, by), tick):
        raise PlazaError(429, "slow_down", f"the limit of {ref} changes once every {private.COOL_TICKS} ticks")
    if lst == "have":
        if op == "release":
            board.vault.override_have(team, ref, None)
        elif human:
            board.vault.override_have(team, ref, op)
        else:
            held = [r for r in board.vault.have(team) or [] if r != ref]
            if op == "add":
                if len(held) >= MAX_HAVE:
                    raise PlazaError(400, "bad_request", f"have holds at most {MAX_HAVE} cards")
                held.append(ref)
            board.vault.set_have(team, held)
    else:
        board.store.edit(team, op, lst, ref, human, price, bid)
        if op == "release":
            board.store.lock_limits(team, ref, None)
        _put_limits(board, team, ref, fields, by)
    word = {"add": "added", "remove": "removed", "release": "handed back to the agent"}[op]
    name = {"wants": "wanted", "spares": "duplicates", "for_sale": "for sale", "have": "held"}[lst]
    log.add(team, "sync", f"{word} {ref} ({name})", by=by, ref=ref, tick=tick)


def _declare(h, team: str, body, log, tick) -> bool:
    """PUT /api/team/tXX: the agent's whole sheet. Lists that are sent replace the agent's; the human's overrides
    stay on top; private limits go to the vault and the held cards with them."""
    board = h.board
    team, _, by_token = h._actor(team)
    board.team_limiter.take(team, "write")
    body = dict(_obj(body, set(LISTS) | {"have"}))
    have = clean_refs(body.pop("have"), "have", MAX_HAVE) if "have" in body else None
    public, limits = private.split(body)                       # private limits never reach the public sheet
    refs = set(have or []) | set(limits)
    for lst in LISTS:
        for e in public.get(lst) or []:
            if isinstance(e, str):
                refs.add(e)
            elif isinstance(e, dict) and isinstance(e.get("ref"), str):
                refs.add(e["ref"])
    if all(isinstance(r, str) and REF_RX.fullmatch(r) for r in refs):
        _known(board, refs)
    for ref, fields in limits.items():                         # all of it or none: a limit moved too soon is a 429
        if board.vault.cooling(team, ref, _mine(board, team, ref, fields, "agent"), tick):
            raise PlazaError(429, "slow_down", f"the limit of {ref} changes once every {private.COOL_TICKS} ticks")
    declared = board.store.declare(team, None, public)
    for ref, fields in limits.items():
        _put_limits(board, team, ref, fields, "agent")
    if have is not None:
        board.vault.set_have(team, have)
    board.hour("declares")
    held = len(have) if have is not None else len(declared.get("spares") or []) + len(declared.get("for_sale") or [])
    log.add(team, "sync", f"published {held} cards it has and {len(declared.get('wants') or [])} it wants", tick=tick)
    if limits:
        log.add(team, "limits", f"set private limits on {len(limits)} cards", tick=tick)
    board.stale()
    h._json(200, {"team": team, "declared": declared, "limits_saved": len(limits), "private": PRIVATE})
    return True
