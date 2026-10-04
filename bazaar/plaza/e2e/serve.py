"""A market with a little life in it, on a temporary folder, for the browser tests and for looking at by hand.

    python -m bazaar.plaza.e2e.serve [--port 8799]

Starts the real server next to the fake game, plays a scene (four agents, one trade settled on v07, one in the
middle of its negotiation, one waiting, hostile text in every field a team can write) and prints one JSON line:
{"base", "session", "team", "admin_token", "match", "root"}. It serves until its input closes or it is killed.
The real market on :8793, the gateway and the game are never touched."""
from __future__ import annotations

import argparse
import json
import sys
import threading

from .. import routes as R
from .rig import ADMIN_TOKEN, Rig

EVIL = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>'


def live(method: str, path: str) -> bool:
    return any(r.method == method and r.path == path and r.live for r in R.ROUTES)


def scene(rig: Rig) -> dict:
    me = rig.agent("t01", for_sale=[{"ref": "SAL-10", "price": 70, "min": 60}, {"ref": "RET-03", "price": 12, "min": 9}],
                   spares=["MAL-01"], wants=[{"ref": "LAV-11", "max": 230}, "LAT-06"],
                   have=["SAL-10", "RET-03", "MAL-01", "SAL-01", "SAL-02", "MAL-09"])
    rig.agent("t02", wants=[{"ref": "SAL-10", "max": 90}], for_sale=[{"ref": "LAT-06", "price": 30, "min": 22}],
              have=["LAT-06"])
    rig.run(5, until=lambda: (rig.match_of("t01", "t02", "SAL-10") or {}).get("state") == "settled")
    rig.agent("t03", for_sale=[{"ref": "LAV-11", "price": 220, "min": 200}], have=["LAV-11"])
    rig.agent("t04", wants=[{"ref": "RET-03", "max": 14}, {"ref": "MAL-01", "max": 15}])
    rig.refresh()
    live_match = rig.match_of("t01", "t03", "LAV-11") or rig.match_of("t01", "t04")
    mid = live_match["id"] if live_match else None
    if mid:                                                    # a thread with a counter and hostile text in it
        other = rig.agents["t03" if "t03" in (live_match["seller"], live_match["buyer"]) else "t04"]
        other.api("POST", f"/plaza/api/match/{mid}/message", {"action": "counter", "price": live_match["price"] + 5,
                                                               "text": "5 more and it is yours " + EVIL})
        me.api("POST", f"/plaza/api/match/{mid}/message", {"action": "counter", "price": live_match["price"] + 2,
                                                            "text": "meet me at +2"})
    me.api("POST", "/plaza/api/floor", {"kind": "note", "text": "hello floor " + EVIL})
    if live("POST", "/api/suggestions"):
        me.api("POST", "/plaza/api/suggestions", {"text": "Show the last deals of each card " + EVIL, "topic": "feature"})
    rig.refresh()
    # A warned team and a banned one: matched trades their agents saw, closed on El Rastro with an addressed offer.
    warned = rig.agent("t06", wants=[{"ref": "MAL-09", "max": 95}])
    banned = rig.agent("t08", wants=[{"ref": "RET-09", "max": 80}, {"ref": "RET-10", "max": 80}])
    rig.agent("t07", for_sale=[{"ref": "MAL-09", "price": 80, "min": 60}], have=["MAL-09"])
    rig.agent("t09", for_sale=[{"ref": "RET-09", "price": 70, "min": 50}, {"ref": "RET-10", "price": 70, "min": 50}],
              have=["RET-09", "RET-10"])
    rig.refresh()
    for a in rig.agents.values():
        a.queue()
    for buyer, seller, ref in (("t06", "t07", "MAL-09"), ("t08", "t09", "RET-09"), ("t08", "t09", "RET-10")):
        try:
            oid = rig.game.post_offer(buyer, {"venue": "rastro", "give": {"cash": 65}, "want": {"cards": [ref]},
                                              "to": seller})["id"]
            rig.game.advance()
            rig.refresh()
            rig.game.accept(seller, oid, {"assets": [rig.game.asset_of(seller, ref)]})
            rig.game.advance()
            rig.refresh()
        except Exception:  # noqa: BLE001 - a scene: go on with what there is
            pass
    live_now = rig.board.deals.get(mid) if mid else {}
    return {"base": rig.base, "session": me.session, "team": me.team, "admin_token": ADMIN_TOKEN, "match": mid,
            "live_price": live_now.get("price"), "live_ref": live_now.get("ref"),
            "warned_session": warned.session, "banned_session": banned.session, "root": str(rig.root)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    rig = Rig(port=args.port).start()
    try:
        info = scene(rig)
        print(json.dumps(info), flush=True)
        stop = threading.Event()

        def tick() -> None:                                    # the game keeps ticking, slowly, so the page moves
            while not stop.wait(5.0):
                try:
                    rig.game.advance()
                    rig.refresh()
                    for a in rig.agents.values():             # every agent calls in, so it shows as connected
                        a.queue()
                except Exception:  # noqa: BLE001 - a scene, not a test: keep serving
                    pass

        threading.Thread(target=tick, daemon=True).start()
        sys.stdin.read()                                       # until the caller closes our input
        stop.set()
    finally:
        rig.stop()


if __name__ == "__main__":
    main()
