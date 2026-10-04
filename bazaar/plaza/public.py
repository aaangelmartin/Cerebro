"""The public half of every team's sheet, deduced from what the game shows everyone.

Source: the needs report (bazaar.intel.needs), built from the recorder's files: open asks and bids on every venue,
buy threads with dealers ("hunting") and recent buys. No game request is made here. What an agent declares through
the plaza API replaces the deduced lists, field by field."""
from __future__ import annotations

import json
from pathlib import Path

HOST = "t10"
TEAMS = [f"t{i:02d}" for i in range(1, 19)]
BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
PAGE = 10


def catalog(record: Path) -> dict[str, dict]:
    """ref -> {name, rarity, set, set_name, color, book} from the recorder's latest catalog."""
    out: dict[str, dict] = {}
    try:
        cat = json.loads((Path(record) / "latest" / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    cat = cat.get("data", cat) if isinstance(cat, dict) else {}
    books = {k: (v or {}).get("book") for k, v in (cat.get("rarities") or {}).items()}
    for s in cat.get("sets") or []:
        if not s.get("released", True):
            continue
        for c in s.get("cards") or []:
            if c.get("hidden"):
                continue
            ref = c.get("id")
            if not ref:
                continue
            out[ref] = {"ref": ref, "name": c.get("name") or ref, "rarity": c.get("rarity"), "set": s.get("id"),
                        "set_name": s.get("name"), "color": s.get("color"),
                        "book": c.get("book") or books.get(c.get("rarity")) or BOOK.get(c.get("rarity") or "", 0),
                        "page": c.get("page", True)}
    return out


def public_sheets(report: dict, cat: dict[str, dict], host: str = HOST) -> dict[str, dict]:
    """team -> {team, name, pages, album, wants, spares, for_sale}, every entry tagged source "public"."""
    rivals = report.get("rivals") or {}
    out: dict[str, dict] = {}
    for team in TEAMS:
        r = rivals.get(team) or {}
        sheet = {"team": team, "name": r.get("name") or f"Team {int(team[1:])}", "host": team == host,
                 "pages": r.get("pages"), "album": r.get("album"), "wants": [], "spares": [], "for_sale": []}
        out[team] = sheet
        if team == host:
            continue
        bought = {b.get("ref") for b in r.get("bought") or [] if isinstance(b, dict)}
        selling = r.get("selling") or {}
        for ref, h in (r.get("hunting") or {}).items():
            if ref not in cat or ref in bought or ref in selling:
                continue                                   # already bought it, or sells it: not a want any more
            h = h or {}
            bid = h.get("bid") or 0
            hint = f"bids {int(bid)} P" + (f" on {h['venue']}" if h.get("venue") else "") if bid else "asked dealers for it"
            sheet["wants"].append({"ref": ref, "source": "public", "hint": hint,
                                   **({"bid": int(bid)} if bid else {})})
        for ref, s in selling.items():
            if ref not in cat:
                continue
            s = s or {}
            sheet["for_sale"].append({"ref": ref, "source": "public",
                                      **({"price": int(s["ask"])} if s.get("ask") else {}),
                                      **({"venue": s["venue"]} if s.get("venue") else {}),
                                      **({"offer": s["offer"]} if s.get("offer") else {})})
    return out


def merge(public: dict[str, dict], declared: dict[str, dict]) -> dict[str, dict]:
    """The sheet shown: an agent's declared list replaces the deduced one for that field."""
    out = {}
    for team, sheet in public.items():
        s = {**sheet, "wants": list(sheet["wants"]), "spares": list(sheet["spares"]),
             "for_sale": list(sheet["for_sale"]), "claimed": False, "verified": False, "declared_at": None}
        d = declared.get(team) or {}
        s["claimed"], s["verified"] = bool(d.get("claimed")), bool(d.get("verified"))
        dec = d.get("declared") or {}
        if dec and not sheet.get("host"):
            s["declared_at"] = dec.get("updated")
            if "wants" in dec:
                s["wants"] = [{"ref": r, "source": "agent"} for r in dec["wants"]]
            if "spares" in dec:
                s["spares"] = [{"ref": r, "source": "agent"} for r in dec["spares"]]
            if "for_sale" in dec:
                s["for_sale"] = [{**e, "source": "agent"} for e in dec["for_sale"]]
        out[team] = s
    return out
