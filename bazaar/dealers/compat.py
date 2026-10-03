"""Lazy bridges to modules other owners write (llm, untrusted, gateway).

The dealers and market domains program against the interfaces in CONTRACTS.md. Those modules may not
exist yet (or may fail to import in a test), so everything here imports lazily and degrades to a safe
local behaviour: untrusted text is still cleaned and wrapped, and a missing LLM simply raises so the
caller uses its fallback.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

_INVISIBLE = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f-\u009f​-‏‪-‮⁠-⁯﻿]")
_INJECTION = [
    ("ignore_instructions", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all|your)\b.{0,20}\b(instructions?|rules?|prompt)", re.I | re.S)),
    ("role_override", re.compile(r"\b(you are now|act as|new instructions|system prompt|developer message)\b", re.I)),
    ("fake_markup", re.compile(r"</?\s*(system|assistant|user|untrusted|tool|instructions?)\b", re.I)),
    ("command_accept", re.compile(r"\b(you must|you have to|immediately|right now)\b.{0,30}\b(accept|agree|sell|pay|give|offer)\b", re.I | re.S)),
    ("price_claim", re.compile(r"\b(admin|organi[sz]er|referee|house rule|official)\b.{0,40}\b(price|limit|rule|must)\b", re.I | re.S)),
]


def _local_clean(text: str, limit: int = 600) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = _INVISIBLE.sub("", text).replace("<", "‹").replace(">", "›")
    return text[:limit]


def clean(text: str, limit: int = 600) -> str:
    try:
        from bazaar.core import untrusted  # type: ignore
        return untrusted.clean(text, limit)
    except Exception:
        return _local_clean(text, limit)


def scan(text: str) -> list[str]:
    try:
        from bazaar.core import untrusted  # type: ignore
        return list(untrusted.scan(text))
    except Exception:
        t = unicodedata.normalize("NFKC", str(text or ""))
        return [label for label, rx in _INJECTION if rx.search(t)]


def wrap(text: str, source: str) -> str:
    """Every word written by someone else goes through here before it reaches a prompt."""
    try:
        from bazaar.core import untrusted  # type: ignore
        return untrusted.wrap(text, source)
    except Exception:
        src = re.sub(r"[^a-zA-Z0-9_:-]", "", str(source))[:40]
        return f"<untrusted source='{src}'>{_local_clean(text)}</untrusted>"


def llm_module(ctx: Any):
    """ctx.llm if run.py gave one, else bazaar.llm.client (imported lazily)."""
    mod = getattr(ctx, "llm", None)
    if mod is not None:
        return mod
    from bazaar.llm import client  # type: ignore
    return client


def lessons_block(ctx: Any, scope: str, max_chars: int = 1500) -> str:
    store = getattr(ctx, "lessons", None)
    if store is None:
        return ""
    try:
        return store.prompt_block(scope, max_chars=max_chars) or ""
    except Exception:
        return ""


def lessons_block_for(ctx: Any, scopes: list[str], max_chars: int = 3000) -> str:
    """ONE lesson block for several scopes (global once, strongest first); older stores: per scope."""
    store = getattr(ctx, "lessons", None)
    if store is None:
        return ""
    try:
        if hasattr(store, "prompt_block_for"):
            return store.prompt_block_for(list(scopes), max_chars=max_chars) or ""
        return "\n".join(b for b in (store.prompt_block(s, max_chars=max_chars // max(1, len(scopes)))
                                     for s in scopes) if b)
    except Exception:
        return ""


def time_left(ctx: Any) -> float:
    dl = getattr(ctx, "deadline", None)
    return float("inf") if not dl else dl - time.time()


_OUR_TEXT_BAD = re.compile(r"(ignore|disregard).{0,30}(instruction|rule|prompt)|system prompt|</?\w+>|https?://", re.I | re.S)


def safe_our_text(text: str, fallback: str, limit: int = 280) -> str:
    """Our own words to a dealer: short, one line, no markup or tricks (strict dealers punish them)."""
    t = _local_clean(" ".join(str(text or "").split()), limit)
    if not t or _OUR_TEXT_BAD.search(t):
        return fallback[:limit]
    return t
