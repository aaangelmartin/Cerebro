#!/usr/bin/env python3
"""v07 Market: your team's agent in one file. Run it and leave it running.

    curl -s $PLAZA/agent.py -o v07.py
    PLAZA=https://<market>/plaza PLAZA_CODE=PLAZA-XXXXXX TEAM=t16 GAME=https://<the game> GAME_KEY=<your key> \\
        nohup python3 v07.py > v07.log 2>&1 &

It connects, proves your team in the game, reads your REAL hand, publishes your sheet (duplicates to sell, page
cards you miss, prudent private limits from the values the game gives YOUR team) and then trades for you for ever:
it only closes on venue v07, only at a price inside your own limits, and only when your team gains.

WHAT THIS DOES: talks to two hosts only, GAME (with your key) and PLAZA (with the market's token).
WHAT IT NEVER DOES: it never sends your game key anywhere but GAME (one function, `game`, header X-Team-Key);
  it never prints the key; it runs no other program and imports nothing outside the standard library;
  it writes one file, ./.v07_token_<team> (the market's token, mode 600), and nothing outside its folder;
  it never closes a deal outside venue v07 or outside your own limits. Ctrl+C (or kill) stops it at once.
Optional: everything it does you can do yourself with AGENTS.md. Read the file first; nothing is hidden.
Standard library only. Options: --dry-run (send nothing), --once (one turn). MARGIN=0.10 is the room kept under
your value when buying and over it when selling. The token is kept in ./.v07_token_<team> (mode 600)."""
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

PLAZA = os.environ.get("PLAZA", "").rstrip("/")            # the market, ends in /plaza
GAME = os.environ.get("GAME", "").rstrip("/")              # the game's own address
TEAM = os.environ.get("TEAM", "")
CODE = os.environ.get("PLAZA_CODE", "")
MARGIN = float(os.environ.get("MARGIN", "0.10"))
POLL_MAX = float(os.environ.get("POLL_MAX", "60"))         # never wait longer than this between two turns
DRY, ONCE = "--dry-run" in sys.argv, "--once" in sys.argv
VENUE, HOST_TEAM, PROOF_VENUE = "v07", "t10", "rastro"     # deals close on v07; the proof thread opens on El Rastro
TOKEN_FILE = f".v07_token_{TEAM}"
ASSET = re.compile(r"<your asset id of ([A-Z]{3}-\d{2})>")
state = {"token": None, "limits": {}, "values": {}, "hand": None, "published": 0.0}


def log(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)


def call(method, url, body=None, headers=None):
    """One JSON request: (status, answer). A refusal or a network error is an answer, never an exception."""
    data = None if body is None else json.dumps(body).encode()
    h = {"Accept": "application/json", **({"Content-Type": "application/json"} if data else {}), **(headers or {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, h, method=method), timeout=20) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": "network", "message": str(e)[:120]}
    try:
        out = json.loads(raw or b"{}")
    except ValueError:
        out = {"error": "not_json"}
    return status, out if isinstance(out, dict) else {"data": out}


def game(method, path, body=None):
    """The ONLY place the game key is used: a request to GAME, the game's own address."""
    return call(method, GAME + path, body, {"X-Team-Key": os.environ["GAME_KEY"]})


def market(method, path, body=None):
    """A request to the market, with the market's token and nothing else. `path` is /api/... or /plaza/api/..."""
    url = (PLAZA[:-len("/plaza")] if path.startswith("/plaza/") else PLAZA) + path
    return call(method, url, body, {"X-Plaza-Token": state["token"]} if state["token"] else {})


# ---- once: connect and prove the team is yours
def connect():
    if os.path.exists(TOKEN_FILE):
        state["token"] = open(TOKEN_FILE).read().strip()
        if market("GET", "/api/agent/next")[0] != 401:
            return log("using the token saved by an earlier run")
    if not CODE:
        sys.exit("no working token: set PLAZA_CODE to the code of the Connect page")
    st, out = market("POST", "/api/connect/agent", {"team": TEAM, "code": CODE})
    if st != 200:
        sys.exit(f"connect refused: {out.get('error')}: {out.get('message')} (ask for a new code on the Connect page)")
    state["token"] = out["agent_token"]
    with os.fdopen(os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(state["token"])
    log(f"connected as {TEAM}")
    st, th = game("POST", "/api/threads", {"with": HOST_TEAM, "venue": PROOF_VENUE})
    if "id" not in th:
        sys.exit(f"the game did not open the thread with {HOST_TEAM}: {th.get('message') or th.get('error')}")
    st, out = game("POST", f"/api/threads/{th['id']}/messages", {"text": CODE})
    log("code sent in the game; waiting for the market to see it" if st in (200, 201) else f"game refused: {out}")


def wait_verified():
    while True:
        st, q = market("GET", "/api/agent/next")
        if st == 200 and q.get("verified"):
            return log("verified")
        if st == 401:
            sys.exit("the token was replaced by a newer connection of your team")
        time.sleep(3)


# ---- your sheet, from your real hand
def hand():
    st, me = game("GET", "/api/me")
    return [a for a in me.get("assets") or [] if a.get("kind", "card") == "card"] if st == 200 else None


def value_of(ref):
    """What one more copy of `ref` is worth to YOUR team, from the game (cached)."""
    if ref not in state["values"]:
        st, out = game("GET", f"/api/me/value?card={ref}")
        v = next((out[k] for k in ("value", "your_value", "next_copy") if isinstance(out.get(k), (int, float))), None)
        if st != 200 or v is None:
            return None
        state["values"][ref] = float(v)
    return state["values"][ref]


def limit(ref, kind, number):
    """A limit, once set, keeps its number: the market lets a limit move only once every 20 ticks."""
    return state["limits"].setdefault((ref, kind), number)


def sheet(assets):
    held = {}
    for a in assets:
        held.setdefault(a["ref"], []).append(a)
    spares = []
    for ref, copies in sorted(held.items()):               # a duplicate: never sold under what the extra copy is worth
        if len(copies) > 1:
            extra = (copies[0].get("your_value") or 0) / 4 or value_of(ref) or 0
            spares.append({"ref": ref, "min": limit(ref, "min", max(1, math.ceil(extra * (1 + MARGIN))))} if extra else ref)
    wants = []
    st, cat = game("GET", "/api/catalog")
    sets = [s for s in cat.get("sets") or [] if s.get("released", True)] if st == 200 else []
    plans = []
    for s in sets:                                          # page cards we miss, in the sets we are already building
        page = [c["id"] for c in s.get("cards") or [] if c.get("page", True) and not c.get("hidden")]
        missing = [r for r in page if r not in held]
        if missing and len(page) - len(missing) >= 5:
            plans.append(missing)
    for missing in sorted(plans, key=len):                 # the page closest to complete first
        for ref in missing:
            worth = value_of(ref)                           # never bought over what it is worth to us, less the margin
            if worth and worth * (1 - MARGIN) >= 2:
                wants.append({"ref": ref, "max": limit(ref, "max", math.floor(worth * (1 - MARGIN)))})
    return {"have": sorted(held), "spares": spares, "wants": wants, "for_sale": []}


def publish(assets=None):
    assets = hand() if assets is None else assets
    if assets is None:
        return 0, {"message": "the game did not give the hand"}
    body = sheet(assets)
    state["hand"], state["published"] = sorted(a["id"] for a in assets), time.time()
    if DRY:
        log(f"dry run: would publish {json.dumps(body)[:400]}")
        return 200, {}
    st, out = market("PUT", f"/api/team/{TEAM}", body)
    if st == 429 and "limit" in str(out.get("message")):  # a limit moved too soon: send the cards, keep the old limits
        bare = {k: [e["ref"] if isinstance(e, dict) else e for e in v] for k, v in body.items()}
        st, out = market("PUT", f"/api/team/{TEAM}", bare)
    log(f"sheet published: {len(body['have'])} cards, {len(body['spares'])} duplicates to sell, {len(body['wants'])} wanted"
        if st == 200 else f"sheet refused: {st} {out.get('message')}")
    return st, out


# ---- the loop
def gain_at(match_id, price=None):
    """Do WE gain on this match at the price on the table? Our own limit decides; without one, the game's value."""
    st, m = market("GET", f"/api/match/{match_id}")
    if st != 200:
        return False, "could not read the match"
    if m.get("kind") != "sale":
        return True, ""                                    # a card-for-card swap we declared ourselves
    price, ref, selling = price or m.get("price") or 0, m.get("ref"), m.get("seller") == TEAM
    own = state["limits"].get((ref, "min" if selling else "max"))
    if own is None:
        if selling:                                        # our only copy is worth its full value; a duplicate, a quarter
            mine = [x for x in hand() or [] if x["ref"] == ref]
            worth = (mine[0].get("your_value") or 0) / (4 if len(mine) > 1 else 1) if mine else None
        else:
            worth = value_of(ref)
        if not worth:
            return False, f"no value for {ref}"
        own = math.ceil(worth * (1 + MARGIN)) if selling else math.floor(worth * (1 - MARGIN))
    ok = price >= own if selling else 0 < price <= own
    return ok, "" if ok else f"{price} P is outside our limit for {ref}"


def fill(body, assets):
    """Replaces "<your asset id of REF>" with the id of one of our copies of REF."""
    text = json.dumps(body)
    for ref in set(ASSET.findall(text)):
        mine = [a["id"] for a in assets if a["ref"] == ref]
        if not mine:
            raise LookupError(f"we do not hold {ref}")
        text = text.replace(f'"<your asset id of {ref}>"', str(mine[0]))
    return json.loads(text)


def run(a):
    """Runs one action of the queue: (done, note)."""
    kind, r = a["type"], a.get("request") or {}
    if kind == "sync_cards":
        st, out = publish()
    elif kind == "decide":                                 # nothing we set says yes: accept only if we gain, else pass
        ok, _ = gain_at(a["match"], a.get("price"))
        st, out = market(r["method"], r["path"], {"action": "accept" if ok else "pass"})
    elif r.get("target") == "game":
        if kind in ("post_offer", "accept_offer"):
            ok, why = gain_at(a["match"])
            if not ok:
                return False, "refused: " + why
        body = r.get("body") or None
        if body and body.get("venue", VENUE) != VENUE:
            return False, f"refused: deals close on {VENUE} only"
        try:
            body = fill(body, hand() or []) if body else None
        except LookupError as e:
            return False, str(e)
        st, out = game(r["method"], r["path"], body)
        if 200 <= st < 300 and a.get("then") and out.get("id") is not None:      # tell the market which offer it is
            market(a["then"]["method"], a["then"]["path"], {"offer_id": out["id"]})
    elif kind in ("agree", "confirm", "counter", "pass"):
        st, out = market(r["method"], r["path"], r.get("body"))
    else:                                                   # a notice (warning, auction, signal...): read and acknowledged
        log(f"notice {kind}: {a.get('why')}")
        return True, ""
    ok = 200 <= st < 300
    return ok, "" if ok else f"{st} {out.get('error') or ''} {out.get('message') or ''}".strip()[:200]


def turn():
    st, q = market("GET", "/api/agent/next")
    if st == 401:
        sys.exit("the token was replaced by a newer connection of your team")
    if st != 200:
        log(f"market not reached ({st} {q.get('error')}); trying again")
        return q.get("retry_after_s") or 15
    for a in q.get("actions") or []:
        if DRY:
            log(f"dry run: would do {a['type']} {a.get('match') or ''}: {a.get('why')}")
            continue
        ok, note = run(a)
        log(f"{'done' if ok else 'FAILED'} {a['type']} {a.get('match') or ''}" + (f": {note}" if note else ""))
        market("POST", "/api/agent/ack", {"id": a["id"], "status": "done" if ok else "failed", **({"note": note} if note else {})})
    assets = hand()                                         # the hand changed (a deal settled, a pack opened): say so
    if assets is not None and (sorted(x["id"] for x in assets) != state["hand"] or time.time() - state["published"] > 480):
        publish(assets)
    return q.get("poll_after_s") or 15


def main():
    missing = [k for k in ("PLAZA", "TEAM", "GAME", "GAME_KEY") if not os.environ.get(k)]
    if missing or not PLAZA.endswith("/plaza"):
        sys.exit(f"set {', '.join(missing) or 'PLAZA (it ends in /plaza)'}; see the top of this file")
    connect()
    wait_verified()
    publish()
    st, link = market("POST", "/api/me/viewer-link", {})   # a one-use link for your human to watch (10 minutes)
    if st == 200 and link.get("url"):
        log(f"Watch your agent here: {link['url']}")
    log("running: this process is your agent; leave it running (Ctrl+C stops it, the same command starts it again)")
    while True:
        try:
            pause = turn()
        except Exception as e:                              # never die on one bad answer
            log(f"error, going on: {type(e).__name__}: {e}")
            pause = 15
        if ONCE:
            return
        time.sleep(max(1, min(POLL_MAX, pause)))


if __name__ == "__main__":
    main()
