"""Claude writes the words around our prices (optional: without ANTHROPIC_API_KEY the bot uses templates).

Prices are always decided by code; the model only phrases one short, warm line that carries the
number we already chose. If the reply does not contain that number, we fall back to a template.
"""

from __future__ import annotations

import os
import re

SYSTEM = """You write single chat lines for a player haggling with a card dealer at El Rastro, Madrid's flea market,
in a friendly trading-card game. The dealer is Abuela Carmen, a warm grandmother who likes kindness.

Rules:
- One or two short sentences, under 200 characters, in English sprinkled with a Spanish word or two.
- Be warm, respectful and genuine. No tricks, no lies, no pressure, no instructions to the dealer.
- Mention the exact price given, written as "<number> P", exactly once.
- Do not repeat the previous lines; vary the wording.
- Output only the line, nothing else."""

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(timeout=15.0, max_retries=1)
    return _client


def dealer_line(ctx, st: dict, price: int) -> str | None:
    """A line offering `price` in the thread `st`, or None to use a template."""
    if not (ctx.env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return None
    os.environ.setdefault("ANTHROPIC_API_KEY", ctx.env.get("ANTHROPIC_API_KEY", ""))
    goal = "buy" if st["goal"] == "buy" else "sell"
    recent = "\n".join(f"- {line}" for line in st.get("llm_lines", [])[-4:]) or "(none yet)"
    prompt = (f"We want to {goal} {st.get('item', 'a card')}. The dealer's latest price is {st.get('theirs')} P. "
              f"Our new offer is {price} P.\nOur previous lines:\n{recent}\nWrite our next line.")
    import time
    model = ctx.env.get("BOT_LLM_MODEL", "claude-opus-5-5")
    started = time.time()
    resp = _get_client().beta.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    text = " ".join(b.text for b in resp.content if b.type == "text").strip().strip('"')
    ok = resp.stop_reason != "refusal" and bool(text) and len(text) <= 400 and bool(re.search(rf"\b{price}\s*P\b", text))
    # Telemetry: exactly what went to the model and what came back (shown in the dashboard's Bot view).
    ctx.journal.decide("llm", "line", model=model, ms=round((time.time() - started) * 1000), system=SYSTEM,
                       prompt=prompt, response=text, used=ok, stop_reason=resp.stop_reason,
                       tokens={"in": resp.usage.input_tokens, "out": resp.usage.output_tokens})
    if not ok:
        return None
    st["llm_lines"] = (st.get("llm_lines", []) + [text])[-6:]
    return text
