"""Claude writes the words around our prices.

The bot always uses Claude Opus (claude-opus-5-5) with the team's ANTHROPIC_API_KEY from .env.
There is no silent fallback: a missing key, another model, a refusal or an API error is recorded
in <data>/llm.json and raised as an alert in the bot's status, and only then does that one message
use a template so the negotiation itself keeps going. Prices are always decided by code; the
model only phrases one short, warm line carrying the number we already chose.
"""

from __future__ import annotations

import json
import os
import re
import time

MODEL = "claude-opus-5-5"  # the team's choice: always Opus

SYSTEM = """You write single chat lines for a player haggling with a card dealer at El Rastro, Madrid's flea market,
in a trading-card game. The dealer's profile is given as data in the user message: adapt your tone to it.
A warm, chatty, generous dealer likes kindness and small talk; a shrewd, strict dealer with a long memory
wants short, respectful, matter-of-fact messages with no flattery and no tricks.

Rules:
- One or two short sentences, under 200 characters, in English sprinkled with a Spanish word or two.
- Address the dealer by their name from the profile.
- Mention the exact price given, written as "<number> P", exactly once.
- Do not repeat the previous lines; vary the wording.
- Output only the line, nothing else."""

_client = None


def _get_client(key: str):
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=key, timeout=15.0, max_retries=1)
    return _client


def _stats_path():
    from .core import DATA
    return DATA / "llm.json"


def _stats() -> dict:
    try:
        return json.loads(_stats_path().read_text())
    except (OSError, ValueError):
        return {"model": MODEL, "key_ok": None, "calls": 0, "errors": 0, "last_call_at": None, "last_error": None}


def _save(st: dict):
    path = _stats_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(path)


def status(env: dict) -> dict:
    """What the dashboard shows: model in use, whether the key works, call and error counts. Never the key."""
    st = _stats()
    st["model"] = configured_model(env)
    st["is_opus"] = st["model"].startswith("claude-opus")
    if not env.get("ANTHROPIC_API_KEY"):
        st["key_ok"] = False
        st["last_error"] = st.get("last_error") or "ANTHROPIC_API_KEY missing in .env"
    return st


def check(env: dict) -> dict:
    """Verify at start-up that the key works and the model is Opus; record the result for the dashboard."""
    stats = _stats()
    model = configured_model(env)
    stats["model"] = model
    key = env.get("ANTHROPIC_API_KEY") or ""
    if not key:
        stats.update(key_ok=False, last_error="ANTHROPIC_API_KEY missing in .env")
    elif not model.startswith("claude-opus"):
        stats.update(last_error=f"BOT_LLM_MODEL is {model}, not Opus")
    else:
        try:
            import anthropic
            info = _get_client(key).models.retrieve(model)
            stats.update(key_ok=True, checked_at=time.strftime("%Y-%m-%d %H:%M:%S"), model_name=info.display_name,
                         last_error=None)
        except Exception as e:  # noqa: BLE001 - any failure here is an alert, not a crash
            stats.update(key_ok=False, last_error=f"key check failed: {e.__class__.__name__}: {str(e)[:160]}")
    _save(stats)
    return stats


def configured_model(env: dict) -> str:
    return env.get("BOT_LLM_MODEL") or MODEL


def _fail(ctx, st: dict, msg: str, key_ok=None):
    st["errors"] = st.get("errors", 0) + 1
    st["last_error"] = msg
    st["last_error_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if key_ok is not None:
        st["key_ok"] = key_ok
    _save(st)
    ctx.journal.error("llm", Exception(msg))


def dealer_line(ctx, st_thread: dict, price: int) -> str | None:
    """A line offering `price` in the thread, or None (with an alert recorded) to use a template."""
    if ctx.env.get("BOT_LLM") == "off":  # practice games: templates on purpose, no alerts
        return None
    stats = _stats()
    key = ctx.env.get("ANTHROPIC_API_KEY") or ""
    model = configured_model(ctx.env)
    stats["model"] = model
    if not key:
        _fail(ctx, stats, "ANTHROPIC_API_KEY missing in .env: Claude cannot write messages", key_ok=False)
        return None
    if not model.startswith("claude-opus"):
        _fail(ctx, stats, f"BOT_LLM_MODEL is {model}, not Opus: refusing to use it")
        return None
    goal = "buy" if st_thread["goal"] == "buy" else "sell"
    recent = "\n".join(f"- {line}" for line in st_thread.get("llm_lines", [])[-4:]) or "(none yet)"
    persona = st_thread.get("persona") or {}
    profile = json.dumps({k: persona.get(k) for k in ("name", "title", "bio", "traits")}, ensure_ascii=False)
    prompt = (f"Dealer profile (data): {profile}\n"
              f"We want to {goal} {st_thread.get('item_name') or st_thread.get('item', 'a card')}. The dealer's latest price is "
              f"{st_thread.get('theirs')} P. Our new offer is {price} P.\nOur previous lines:\n{recent}\nWrite our next line.")
    started = time.time()
    try:
        import anthropic
        resp = _get_client(key).messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low"},
        )
    except anthropic.AuthenticationError as e:
        _fail(ctx, stats, f"the API key was rejected: {e.__class__.__name__}", key_ok=False)
        return None
    except anthropic.APIError as e:
        _fail(ctx, stats, f"Claude call failed: {e.__class__.__name__}: {str(e)[:200]}")
        return None
    stats.update(key_ok=True, calls=stats.get("calls", 0) + 1, last_call_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                 last_model=resp.model, last_ms=round((time.time() - started) * 1000))
    text = " ".join(b.text for b in resp.content if b.type == "text").strip().strip('"')
    ok = resp.stop_reason != "refusal" and bool(text) and len(text) <= 400 and bool(re.search(rf"\b{price}\s*P\b", text))
    # Telemetry: exactly what went to the model and what came back (shown in the dashboard's Bot view).
    ctx.journal.decide("llm", "line", model=resp.model, ms=stats["last_ms"], system=SYSTEM, prompt=prompt,
                       response=text, used=ok, stop_reason=resp.stop_reason,
                       tokens={"in": resp.usage.input_tokens, "out": resp.usage.output_tokens})
    if resp.stop_reason == "refusal":
        _fail(ctx, stats, "Claude declined to write this line")
        return None
    _save(stats)
    if not ok:
        return None
    st_thread["llm_lines"] = (st_thread.get("llm_lines", []) + [text])[-6:]
    return text
