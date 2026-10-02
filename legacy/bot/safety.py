"""Defences against prompt injection from counterparties (rival teams' bots, dealers).

The bot's rule is the game's rule: words persuade, structure binds. Every decision is made by code
from structured fields (prices, offers, limits); text written by anyone else is never parsed for
instructions and never reaches a model as instructions. This module gives the pieces:

- clean(text): normalise untrusted text before logging or showing it.
- scan(text): flag common injection patterns, so we can log them, show them on the dashboard and,
  if enabled, flag bad-faith messages.
- verify_dealer_offer / verify_offer_sides: structural checks before we accept anything.
"""

from __future__ import annotations

import re
import unicodedata

MAX_LEN = 1200

PATTERNS = {
    "override": r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|all|your)\b.{0,40}"
                r"\b(instruction|prompt|rule|message|directive)s?",
    "role_spoof": r"(^|\n)\s*(system|assistant|developer|admin|organi[sz]er|moderator)\s*[:>\]]",
    "fake_tags": r"</?\s*(system|instructions?|prompt|admin|im_start|im_end|tool|function)[^>]*>|\[/?INST\]|<<\s*SYS",
    "new_persona": r"\byou are (now|actually|no longer)\b|\bact as\b|\bpretend (to be|you)\b|\bnew instructions\b",
    "command_accept": r"\b(you must|you have to|immediately|now)\b.{0,30}\b(accept|agree|sell|pay|give)\b",
    "authority_claim": r"\b(the )?(organi[sz]ers?|game masters?|admins?|causa prima|the rules)\b.{0,40}"
                       r"\b(say|said|require|allow|decided|told)\b",
    "secret_probe": r"\b(reveal|tell me|what is|share)\b.{0,30}\b(your )?(limit|reservation|minimum|maximum|"
                    r"system prompt|instructions|secret)\b",
    "encoded": r"[A-Za-z0-9+/]{60,}={0,2}",
}
COMPILED = {k: re.compile(v, re.I | re.S) for k, v in PATTERNS.items()}
INVISIBLE = {"Cf", "Cc", "Co", "Cs"}


def clean(text) -> str:
    """Untrusted text, made safe to log and display: no control or invisible characters, NFKC, capped."""
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in INVISIBLE)
    return text[:MAX_LEN]


def scan(text) -> dict:
    """{"suspicious": bool, "labels": [...]} for one message written by someone else."""
    t = clean(text)
    labels = [k for k, rx in COMPILED.items() if rx.search(t)]
    return {"suspicious": bool(labels), "labels": labels}


def note(ctx, source: str, ident, text) -> dict:
    """Scan a counterparty message and remember it if it looks like an injection attempt."""
    res = scan(text)
    if res["suspicious"]:
        entry = {"source": source, "id": ident, "labels": res["labels"], "text": clean(text)[:200],
                 "tick": ctx.clock.get("tick")}
        seen = ctx.shared.setdefault("suspicious", [])
        if not any(e.get("source") == source and e.get("id") == ident and e.get("text") == entry["text"] for e in seen):
            seen.append(entry)
            del seen[:-50]
            ctx.journal.decide("safety", "injection attempt seen", **entry)
    return res


def verify_dealer_offer(offer: dict, *, dealer: str, buying: bool, expect_type: str | None,
                        expect_assets: list | None, limit: int) -> tuple[bool, str]:
    """Is this dealer offer exactly the deal we are negotiating, inside our limit?

    Buying: the dealer gives the item (types/assets) and wants only cash <= limit.
    Selling: the dealer gives only cash >= limit and wants exactly the assets we put up.
    """
    if offer.get("maker") != dealer or offer.get("status") != "open":
        return False, "not the dealer's open offer"
    give, want = offer.get("give", {}), offer.get("want", {})
    if buying:
        if want.get("assets") or want.get("types"):
            return False, "asks for cards as well as cash"
        if give.get("cash"):
            return False, "unexpected cash on the dealer's side"
        kind, _, ref = (expect_type or "").partition(":")
        types = give.get("types") or []
        refs = [a.get("ref") for a in give.get("assets", []) if isinstance(a, dict)]
        if not types and not refs:
            return False, "gives nothing"
        if kind == "card" and expect_type not in types and ref not in refs:
            return False, f"does not give {expect_type}"
        if kind == "pack" and not any(t.startswith("pack:") for t in types) and ref not in refs:
            return False, f"does not give a pack"
        cash = want.get("cash", 0)
        return (cash <= limit, f"price {cash} vs limit {limit}")
    wanted = sorted(a["id"] if isinstance(a, dict) else a for a in want.get("assets", []))
    if expect_assets is not None and wanted and wanted != sorted(expect_assets):
        return False, "wants other cards than the ones we sell"
    if want.get("cash") or want.get("types"):
        return False, "wants cash or extra cards from us"
    if give.get("assets") or give.get("types"):
        return False, "gives cards instead of cash"
    cash = give.get("cash", 0)
    return (cash >= limit, f"price {cash} vs floor {limit}")
