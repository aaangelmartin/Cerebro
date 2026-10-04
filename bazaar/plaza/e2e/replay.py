"""Does the market read the game's REAL events? Replays the recorded feed against a test instance.

    .venv/bin/python -m bazaar.plaza.e2e.replay [path/to/events.jsonl] [path/to/record]

For every trade between two teams in the recording (Saturday: 11 on v07, 126 on other venues) it starts a market
on a temporary folder with the real catalog, connects and proves the two teams, puts an equivalent match in front
of their agents (same seller, buyer and card, proposed one tick before the first offer), then appends the game's
own lines, untouched: the offers either team listed for that card, their cancellations and the settlement. It
reports the state the match ends in, the ids it stored and who was struck.

Expected: a settlement on v07 -> `settled`; one on another venue -> `settled_elsewhere`; a strike only when the
feed shows an offer addressed between the two teams, posted after the proposal, on the venue where it closed.
The recording is only read; nothing is sent to the game or to the real market."""
from __future__ import annotations

import collections
import json
import shutil
import sys
from pathlib import Path

from .. import matcher
from ..feed import norm_offer
from .rig import Rig

REPO = Path(__file__).parents[3]
EVENTS = REPO / "bazaar" / "data" / "live" / "events.jsonl"
RECORD = REPO / "bazaar" / "data" / "record"
LOOK_BACK = 70                       # ticks before the settlement in which an offer could still be open


def is_team(x) -> bool:
    return isinstance(x, str) and x[:1] == "t" and x[1:].isdigit()


def load(path: Path):
    """(team-to-team settlements, offers listed by id, cancellations by offer id), each with its raw line."""
    trades, listed, cancelled, shapes = [], {}, collections.defaultdict(list), collections.Counter()
    with path.open("rb") as f:
        for raw in f:
            if not (b'"settlement"' in raw or b'"offer.listed"' in raw or b'"offer.cancelled"' in raw):
                continue
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            kind = e.get("type")
            if kind == "offer.listed":
                o = norm_offer(p.get("offer") if isinstance(p.get("offer"), dict) else p)
                if o and isinstance(o.get("id"), int):
                    listed[o["id"]] = {**o, "tick": e.get("tick"), "raw": raw}
            elif kind == "offer.cancelled":
                oid = p.get("offer")
                oid = oid.get("id") if isinstance(oid, dict) else oid
                cancelled[oid].append({"tick": e.get("tick"), "raw": raw})
            elif kind == "settlement":
                shapes[tuple(sorted(p))] += 1
                parties = p.get("parties") or []
                if len(parties) == 2 and all(is_team(x) for x in parties) and p.get("items"):
                    trades.append({"e": e, "p": p, "raw": raw})
    return trades, listed, cancelled, shapes


def case(t: dict, listed: dict, cancelled: dict, catalog: Path) -> dict:
    p, tick = t["p"], t["e"]["tick"]
    item = next(i for i in p["items"] if i.get("ref"))
    seller, buyer, ref = item["frm"], item["to"], item["ref"]
    refs = {i["ref"] for i in p["items"] if i.get("ref")}
    offers = [o for o in listed.values() if o["maker"] in (seller, buyer) and o["ref"] in refs
              and tick - LOOK_BACK <= (o["tick"] or 0) <= tick]
    open_at = [o for o in offers if not any(c["tick"] <= tick for c in cancelled.get(o["id"], []))]
    here = [o for o in open_at if o["venue"] == p["venue"]]
    addressed = [o for o in here if o.get("to") in (seller, buyer)]
    how = "addressed" if addressed else "public" if here else "no offer in the feed"
    lines = sorted([(o["tick"] or 0, 0, o["raw"]) for o in offers]
                   + [(c["tick"] or 0, 1, c["raw"]) for o in offers for c in cancelled.get(o["id"], []) if c["tick"] <= tick]
                   + [(tick, 2, t["raw"])])
    first = min(x[0] for x in lines)
    out = {"tick": tick, "venue": p["venue"], "seller": seller, "buyer": buyer, "ref": ref, "price": p.get("price"),
           "settlement": p.get("settlement"), "items": len(p["items"]), "how": how,
           "offer_in_feed": (addressed or here or [{}])[0].get("id")}
    if seller == "t10" or buyer == "t10":
        return {**out, "state": "skipped: the host is never in a match"}
    rig = Rig()
    try:
        shutil.copy(catalog, rig.game.record / "latest" / "catalog.json")
        rig.game.tick = first - 1
        rig.game.write_state()
        rig.start()
        a, b = rig.agent(seller), rig.agent(buyer)
        rig.refresh()
        card = rig.board.get()["cat"].get(ref) or {}
        cand = {"kind": "sale", "seller": seller, "buyer": buyer, "ref": ref, "name": card.get("name"),
                "rarity": card.get("rarity"), "price": int(p.get("price") or 0) or 1, "basis": "forced", "saves": 0,
                "last_of_page": False, "priority": 0, "confidence": "forced", "score": 99.0, "why": "replay"}
        cand["id"] = matcher.match_id(cand)
        rig.board.deals.tick = first - 1
        rig.board.deals.force(cand)
        rig.board.stale()
        rig.refresh()
        a.queue()
        b.queue()                                              # both agents have now seen the proposal
        with (rig.game.live / "events.jsonl").open("ab") as f:
            for _, _, raw in lines:
                f.write(raw if raw.endswith(b"\n") else raw + b"\n")
        rig.game.tick = tick
        rig.game.write_state()
        rig.refresh()
        rig.refresh()
        m = rig.board.deals.get(cand["id"])
        view = rig.board.strikes.view() if hasattr(rig.board, "strikes") else {}
        struck = sorted(team for team, row in ((view.get("teams") or {}).items() if isinstance(view.get("teams"), dict)
                                               else [(r.get("team"), r) for r in view.get("teams") or []])
                        if (row.get("strikes") if isinstance(row.get("strikes"), int) else len(row.get("strikes") or [])))
        return {**out, "state": m["state"], "kept_settlement": m.get("settlement"), "kept_venue": m.get("settled_venue"),
                "kept_offer": m.get("offer"), "kept_price": m.get("price"), "struck": struck}
    except Exception as e:  # noqa: BLE001 - one bad case is a finding, not the end of the replay
        return {**out, "state": f"error: {type(e).__name__}: {e}"}
    finally:
        rig.stop()


def main() -> int:
    events = Path(sys.argv[1]) if len(sys.argv) > 1 else EVENTS
    record = Path(sys.argv[2]) if len(sys.argv) > 2 else RECORD
    trades, listed, cancelled, shapes = load(events)
    rows = [case(t, listed, cancelled, record / "latest" / "catalog.json") for t in trades]
    ours = [r for r in rows if r["venue"] == "v07"]
    theirs = [r for r in rows if r["venue"] != "v07" and not r["state"].startswith("skipped")]
    wrong = [r for r in ours if r["state"] != "settled" or r.get("kept_settlement") != r["settlement"]] \
        + [r for r in theirs if r["state"] != "settled_elsewhere"]
    false_strikes = [r for r in theirs if r.get("struck") and r["how"] != "addressed"] + [r for r in ours if r.get("struck")]
    table = collections.Counter((("v07" if r["venue"] == "v07" else "another venue"), r["how"], r["state"],
                                 "struck: " + (",".join(r.get("struck") or []) and "yes" or "nobody")) for r in rows)
    result = {"events": str(events), "settlement_shapes": {", ".join(k): n for k, n in shapes.items()},
              "team_trades": len(rows), "on_v07": len(ours), "elsewhere": len(theirs), "wrong": wrong,
              "false_strikes": false_strikes, "table": [{"venue": k[0], "offer": k[1], "state": k[2], "strike": k[3], "n": n}
                                                        for k, n in sorted(table.items())], "rows": rows}
    (Path(__file__).parent / "replay_result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{len(rows)} real trades between teams: {len(ours)} on v07, {len(theirs)} elsewhere")
    for row in result["table"]:
        print(f"  {row['n']:4d}  {row['venue']:14s} {row['offer']:22s} -> {row['state']:28s} {row['strike']}")
    print(f"wrong state or id: {len(wrong)}; strikes without an addressed offer: {len(false_strikes)}")
    for r in (wrong + false_strikes)[:12]:
        print("  ", {k: r.get(k) for k in ("tick", "venue", "seller", "buyer", "ref", "how", "state", "struck", "settlement", "kept_settlement")})
    return 1 if wrong or false_strikes else 0


if __name__ == "__main__":
    sys.exit(main())
