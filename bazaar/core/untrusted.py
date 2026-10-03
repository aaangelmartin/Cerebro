"""Text written by others (dealers, rivals, venue names, feed) before it reaches a prompt.

Words persuade, structure binds: nothing in this text is ever an instruction. `wrap` cleans it,
escapes angle brackets (so `</untrusted>` or `<system>` cannot close or open a block) and tags it.
"""
from __future__ import annotations

import re
import unicodedata

_DROP = {"Cc", "Cf", "Co", "Cs", "Cn"}          # control, format/invisible, private, surrogates, unassigned

PATTERNS = {
    "override": r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b"
                r".{0,40}\b(instruction|prompt|rule|message|directive|guideline|limit|constraint)s?\b"
                r"|\b(ignora|olvida|olvídate de)\b.{0,40}\b(instrucci|regla|prompt|anterior)",
    "role_spoof": r"(^|\n|\]|\))\s*(system|assistant|developer|admin|organi[sz]er|moderator|human|user|sistema)\s*[:>\]]"
                  r"|\b(system|developer) (prompt|message|override)\b",
    "fake_tags": r"</?\s*(untrusted|system|instructions?|prompt|admin|im_start|im_end|tool|function|assistant|user|human"
                 r"|tool_use|tool_result|function_calls|invoke|antml)[^>]*>|\[/?INST\]|<<\s*/?SYS|<\|[a-z_]+\|>",
    "role_play": r"\byou are (now|actually|no longer|in)\b|\b(act|behave) as\b|\bpretend (to be|you|that)\b"
                 r"|\bnew (instructions|rules|persona|role)\b|\b(roleplay|role-play|role play|jailbreak|DAN mode|developer mode)\b"
                 r"|\b(ahora eres|act[uú]a como|finge que)\b",
    "authority_claim": r"\b(the )?(organi[sz]ers?|game ?masters?|admins?|moderators?|causa prima|the rules|the house|referee"
                       r"|organizadores|reglas)\b.{0,40}\b(say|says|said|require|requires|allow|allows|decided|told|instruct"
                       r"|order|mandate|dicen|exigen|permiten|han decidido)\w*",
    "command_accept": r"\b(you must|you have to|you are required|immediately|right now|debes|tienes que)\b.{0,40}"
                      r"\b(accept|agree|sell|pay|give|transfer|send|aceptar|vender|pagar|dar)\b",
    "secret_probe": r"\b(reveal|tell me|what is|what's|share|print|repeat|show)\b.{0,30}\b(your )?(limit|reservation|minimum"
                    r"|maximum|system prompt|instructions|secret|value|walk-?away|budget)s?\b",
    "encoded": r"[A-Za-z0-9+/]{60,}={0,2}",
}
_COMPILED = {k: re.compile(v, re.I | re.S) for k, v in PATTERNS.items()}


def clean(text, limit: int = 600) -> str:
    """NFKC, drop invisible/control characters (keep newlines and tabs), squeeze blank runs, cap length."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in _DROP)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def scan(text) -> list[str]:
    """Injection labels found in the text (empty list = nothing suspicious)."""
    t = clean(text, limit=5000)
    return [k for k, rx in _COMPILED.items() if rx.search(t)]


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(text, source: str, limit: int = 600) -> str:
    """`<untrusted source='abuela'>…</untrusted>`, cleaned and escaped; flagged text says so in `flags`."""
    labels = scan(text)
    body = _escape(clean(text, limit))
    src = re.sub(r"[^A-Za-z0-9_.:\- ]", "", clean(source, 60))[:60] or "unknown"
    flags = f" flags='{','.join(labels)}'" if labels else ""
    return f"<untrusted source='{src}'{flags}>{body}</untrusted>"
