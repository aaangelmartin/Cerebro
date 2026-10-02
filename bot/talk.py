"""The words around our prices.

Words never move prices (only the structured price does), but dealers remember how they were
treated: Abuela likes kindness, and some dealers call the same words again without a new price
spam. So every message is polite and different. If ANTHROPIC_API_KEY is set, Claude writes the
line (bot/llm.py); otherwise we rotate templates.
"""

from __future__ import annotations

import random

BUY = [
    "Hola, Abuela Carmen! Que bonito puesto. Would {p} P be all right for the {item}? Thank you so much.",
    "Abuela, you are very kind. I am saving for my album, could we say {p} P?",
    "Gracias, cariño! I have eaten, don't worry. {p} P is what I can manage today.",
    "What a lovely morning at El Rastro. Let me stretch a little: {p} P?",
    "My grandmother collected cards too, she would love your stall. {p} P, por favor?",
    "I really want this one for my page. {p} P, and I promise to come back often.",
    "You drive a fair bargain, Abuela. One more step from me: {p} P.",
]
SELL = [
    "Hola, Abuela! I have a spare {item} for your stall, would {p} P suit you?",
    "It is in very good condition, Abuela, kept it in a sleeve. {p} P?",
    "Your grandchildren will love it. Let me come down a little: {p} P.",
    "Gracias, cariño. I can do {p} P for this one.",
    "A fair price for both of us, I think: {p} P.",
    "One more step towards you, Abuela: {p} P.",
]


def say_text(ctx, st: dict, price: int) -> str:
    """One polite line offering `price` for the thread's item, never the same as the last one."""
    try:
        from .llm import dealer_line
        line = dealer_line(ctx, st, price)
        if line:
            return line
    except Exception as e:  # noqa: BLE001 - words are optional, prices are not
        ctx.journal.error("talk", e)
    pool = BUY if st["goal"] == "buy" else SELL
    used = st.setdefault("lines", [])
    fresh = [i for i in range(len(pool)) if i not in used[-len(pool) + 1:]] or list(range(len(pool)))
    i = random.choice(fresh)
    used.append(i)
    return pool[i].format(p=price, item=st.get("item", "card"))
