"""Calls to Claude with a deadline, key failover, spend accounting and a log line per attempt.

    from bazaar.llm import client
    r = client.ask(purpose="duels", system=client.cached_system(stable, volatile),
                   messages=[{"role": "user", "content": "..."}], deadline=sit.deadline)

`model=None` lets the router choose (Opus, or Sonnet past DEGRADE_AT of the day cap).
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .. import config
from ..core import ledger as _ledger
from .router import KeyRouter, LLMTimeout, LLMUnavailable, cost_usd

__all__ = ["LLMResult", "LLMUnavailable", "LLMTimeout", "ask", "race", "spend_today", "cached_system", "router"]

EFFORT = {config.OPUS: "low", config.SONNET: "low"}    # output_config.effort per model (SDK 1.11 supports it)
# Opus/Sonnet 5.5 refuse tool_choice "tool"/"any" (400, measured): they get "auto", so the prompt must ask
# for the tool and callers must handle a text-only answer.
NO_FORCED_TOOL = {config.OPUS, config.SONNET}
DEFAULT_TIMEOUT_S = 60.0
MIN_CALL_S = 0.5                   # don't start an attempt with less time than this
MAX_ATTEMPTS = 6
COOLDOWN_S = {"rate": 15.0, "overloaded": 5.0, "server": 3.0, "network": 2.0, "timeout": 2.0}


@dataclass
class LLMResult:
    text: str
    tool_calls: list[dict]
    model: str
    key: str                       # key label ("A"), never the key
    usage: dict
    cost_usd: float
    latency_s: float
    stop_reason: str = ""
    extra: dict = field(default_factory=dict)


# --- process-wide state (tests swap these) ------------------------------------------
_router: KeyRouter | None = None
_ledger_obj = None
_clients: dict[str, object] = {}
_lock = threading.Lock()


def router() -> KeyRouter:
    global _router
    with _lock:
        if _router is None:
            _router = KeyRouter()
        return _router


def set_router(r: KeyRouter | None):
    global _router
    with _lock:
        _router = r


def set_ledger(lg):
    global _ledger_obj
    _ledger_obj = lg


def _log(rec: dict):
    try:
        (_ledger_obj or _ledger.default()).append("llm", rec)
    except Exception:          # logging must never break a decision
        pass


def make_client(key: str):
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=0)


def _client(label: str, key: str):
    with _lock:
        c = _clients.get(label)
        if c is None:
            c = _clients[label] = make_client(key)
        return c


def cached_system(stable_text: str, volatile_text: str = "") -> list[dict]:
    """System blocks with the cache breakpoint after the stable prefix (tools + this block are cached)."""
    blocks = [{"type": "text", "text": stable_text, "cache_control": {"type": "ephemeral"}}]
    if volatile_text:
        blocks.append({"type": "text", "text": volatile_text})
    return blocks


# --- errors ---------------------------------------------------------------------
def _classify(exc: Exception) -> tuple[str, float]:
    """('dead'|'cool'|'timeout'|'fatal', cooldown seconds)."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    if "timeout" in name.lower() or "timed out" in msg:
        return "timeout", COOLDOWN_S["timeout"]
    if status in (401, 403) or "credit balance" in msg or "billing" in msg:
        return "dead", 0.0
    # a key the API rejects for what it is (e.g. an admin key with no workspace) can never work: drop it, try the next
    if "workspace" in msg or "api key" in msg or "x-api-key" in msg or "invalid_api_key" in msg:
        return "dead", 0.0
    if status == 429:
        retry = _retry_after(exc)
        return "cool", retry if retry is not None else COOLDOWN_S["rate"]
    if status == 529 or "overloaded" in msg:
        return "cool", COOLDOWN_S["overloaded"]
    if isinstance(status, int) and status >= 500:
        return "cool", COOLDOWN_S["server"]
    if status is None and ("connection" in name.lower() or "connection" in msg):
        return "cool", COOLDOWN_S["network"]
    return "fatal", 0.0


def _retry_after(exc) -> float | None:
    try:
        v = exc.response.headers.get("retry-after")
        return min(60.0, float(v)) if v else None
    except Exception:
        return None


# --- the call ---------------------------------------------------------------------
def _parse(resp) -> tuple[str, list[dict], dict, str]:
    text, calls = [], []
    for b in getattr(resp, "content", None) or []:
        t = getattr(b, "type", None)
        if t == "text":
            text.append(b.text)
        elif t == "tool_use":
            calls.append({"id": b.id, "name": b.name, "input": b.input})
    u = getattr(resp, "usage", None)
    usage = {k: int(getattr(u, k, 0) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                       "cache_creation_input_tokens")} if u else {}
    return "".join(text), calls, usage, str(getattr(resp, "stop_reason", "") or "")


def _summary(messages: list) -> str:
    try:
        c = messages[-1]["content"]
        if isinstance(c, list):
            c = " ".join(b.get("text", "") or str(b.get("content", "")) for b in c if isinstance(b, dict))
        return str(c)[-400:]
    except Exception:
        return ""


def ask(*, purpose: str, system: str | list, messages: list, tools: list | None = None,
        tool_choice: dict | None = None, model: str | None = None, max_tokens: int = 1200,
        deadline: float | None = None, temperature: float | None = None,
        _abandoned: threading.Event | None = None, effort: str | None = None) -> LLMResult:
    r = router()
    _check_purpose_cap(r, purpose)
    used = r.resolve(model)
    if model and used != model:
        _log({"purpose": purpose, "event": "degraded", "asked": model, "model": used, "day_usd": r.day_spent()})
    tried: set[str] = set()
    last_err = "no attempt"
    for attempt in range(MAX_ATTEMPTS):
        remaining = None if deadline is None else deadline - time.time()
        if remaining is not None and remaining < MIN_CALL_S:
            raise LLMTimeout(f"{purpose}: deadline reached ({last_err})")
        picked = r.pick(exclude=tried)
        if picked is None:
            ready = r.next_ready()
            if ready is None:
                raise LLMUnavailable(f"{purpose}: no usable key ({last_err})")
            wait = ready - time.time()
            if deadline is not None and time.time() + max(wait, 0) + MIN_CALL_S > deadline:
                raise LLMTimeout(f"{purpose}: keys cooling past the deadline ({last_err})")
            time.sleep(max(0.0, min(wait, 30.0)))
            continue
        label, key = picked
        tried.add(label)
        timeout = DEFAULT_TIMEOUT_S if remaining is None else max(MIN_CALL_S, min(remaining, DEFAULT_TIMEOUT_S))
        kwargs = {"model": used, "max_tokens": max_tokens, "system": system, "messages": messages, "timeout": timeout}
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            if used in NO_FORCED_TOOL and tool_choice.get("type") in ("tool", "any"):
                tool_choice = {"type": "auto"}
            kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            kwargs["temperature"] = temperature
        if used in EFFORT:
            kwargs["output_config"] = {"effort": effort or EFFORT[used]}
        t0 = time.time()
        try:
            resp = _client(label, key).messages.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - every failure is classified below
            kind, cool = _classify(e)
            latency = time.time() - t0
            last_err = f"{type(e).__name__}: {str(e)[:200]}"
            _log({"purpose": purpose, "model": used, "key": label, "attempt": attempt, "latency_s": round(latency, 3),
                  "error": last_err, "error_kind": kind})
            if kind == "dead":
                r.mark_dead(label, last_err)
            elif kind in ("cool", "timeout"):
                r.cooldown(label, cool)
                if kind == "timeout" and deadline is not None and time.time() >= deadline - MIN_CALL_S:
                    raise LLMTimeout(f"{purpose}: {last_err}") from None
            else:
                raise LLMUnavailable(f"{purpose}: {last_err}") from None
            continue
        latency = time.time() - t0
        text, calls, usage, stop = _parse(resp)
        cost = r.record(label, used, usage, purpose)
        _log({"purpose": purpose, "model": used, "key": label, "attempt": attempt, "latency_s": round(latency, 3),
              "usage": usage, "cost_usd": round(cost, 6), "stop": stop, "prompt": _summary(messages),
              "text": text[:600], "tools": [c["name"] for c in calls],
              "late": bool(deadline and time.time() > deadline), "abandoned": bool(_abandoned and _abandoned.is_set())})
        return LLMResult(text, calls, used, label, usage, cost, latency, stop)
    raise LLMUnavailable(f"{purpose}: {MAX_ATTEMPTS} attempts failed ({last_err})")


def _check_purpose_cap(r, purpose: str) -> None:
    """The brain may cap one purpose's day spend (brain.strategy budgets.llm_usd_per_day); over it, the caller
    falls back to code (LLMUnavailable). Never raises for any other reason."""
    try:
        from bazaar.brain.strategy import llm_cap
        cap = llm_cap(purpose)
        if cap is None:
            return
        spent = float((r.summary().get("by_purpose") or {}).get(purpose) or 0.0)
    except Exception:  # noqa: BLE001
        return
    if spent >= cap:
        raise LLMUnavailable(f"{purpose}: the brain's day cap {cap} $ is spent ({spent:.2f} $)")


def race(*, models: list[str], valid: Callable[[LLMResult], bool] | None = None, **kw) -> LLMResult:
    """Ask several models at once; the first valid answer wins. Losers keep running in the background
    and their cost is still recorded when they finish (ask() accounts every completed call)."""
    deadline = kw.get("deadline")
    q: queue.Queue = queue.Queue()
    done = threading.Event()

    def run(m):
        try:
            q.put(("ok", ask(model=m, _abandoned=done, **kw)))
        except Exception as e:  # noqa: BLE001
            q.put(("err", e))

    for m in models:
        threading.Thread(target=run, args=(m,), daemon=True, name=f"llm-race-{m}").start()
    errors: list[Exception] = []
    try:
        while len(errors) < len(models):
            timeout = None if deadline is None else max(0.0, deadline - time.time())
            try:
                status, val = q.get(timeout=timeout)
            except queue.Empty:
                raise LLMTimeout(f"race {models}: deadline reached") from None
            if status == "ok" and (valid is None or valid(val)):
                return val
            errors.append(val if status == "err" else LLMUnavailable(f"{val.model}: invalid answer"))
    finally:
        done.set()
    if any(isinstance(e, LLMTimeout) for e in errors):
        raise LLMTimeout(f"race {models}: {errors}")
    raise LLMUnavailable(f"race {models}: {errors}")


def spend_today() -> dict:
    return router().summary()
