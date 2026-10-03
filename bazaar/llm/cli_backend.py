"""Second LLM backend for el cerebro: the Claude Code CLI on this Mac (the humans' subscription login).

The brain's plans and its council votes are slow, expensive and not latency-critical, so they can run through
`claude -p` instead of the API keys. The call is pure text in, JSON out:

- no tools (`--tools ""`), no MCP servers, no settings, hooks, skills or CLAUDE.md (`--safe-mode`), no saved session;
- the working directory is an empty temp dir outside the repo;
- the environment is cleaned of every API key and provider switch, so the CLI uses the subscription login;
- the answer is forced into the tool's JSON schema (`--json-schema`) and comes back as `structured_output`.

The subscription is shared with the humans' interactive session, so calls are capped (per hour, one at a time,
across processes) and a usage-limit answer backs the backend off. State lives in data/live/mac_backend.json so
the API can show it. control.json: `brain_backend` = "api" | "mac" | "auto", `mac_calls_per_hour`.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .. import config

MODES = ("api", "mac", "auto")
DEFAULT_MODE = "api"                 # the live control file sets "auto"; tests and the sim never call the CLI
DEFAULT_CALLS_PER_HOUR = 20
CALLS_PER_HOUR_MIN, CALLS_PER_HOUR_MAX = 1, 120
TIMEOUT_S = 150.0
BACKOFF_LIMIT_S = 600.0              # usage / rate limit of the subscription
BACKOFF_FAIL_S = 300.0               # timeout, crash or two invalid answers in a row
MODEL = "opus"
MODEL_LABEL = "claude-cli"
KEY_LABEL = "MAC"
STATE_FILE = "mac_backend.json"
LOCK_FILE = "mac_backend.lock"
LIMIT_WORDS = ("usage limit", "rate limit", "limit reached", "limit will reset", "too many requests", "overloaded")
STRIP_ENV_EXACT = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_CUSTOM_HEADERS")
STRIP_ENV_PREFIX = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_")
JSON_RULE = ("\n\nAnswer ONLY with one JSON object that matches the required schema: no prose before or after it, "
             "no code fences.")


class CLIError(Exception):
    """The CLI call failed. kind: "limit" | "timeout" | "invalid" | "busy" | "cap" | "error"."""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(f"{kind}: {message}"[:300])
        self.kind = kind


# --------------------------------------------------------------------------- control and shared state
def _live(live: Path | None = None) -> Path:
    return Path(live or config.LIVE)


def _control(live: Path | None = None) -> dict:
    try:
        return json.loads((_live(live) / "control.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def mode(live: Path | None = None, ctl: dict | None = None) -> str:
    m = (ctl if ctl is not None else _control(live)).get("brain_backend")
    return m if m in MODES else DEFAULT_MODE


def calls_per_hour(live: Path | None = None, ctl: dict | None = None) -> int:
    v = (ctl if ctl is not None else _control(live)).get("mac_calls_per_hour")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return DEFAULT_CALLS_PER_HOUR
    return int(max(CALLS_PER_HOUR_MIN, min(CALLS_PER_HOUR_MAX, v)))


def validate_control(body: dict) -> dict:
    """The Mac-backend fields of POST /control, validated. Raises ValueError."""
    out: dict[str, Any] = {}
    if "brain_backend" in body:
        if body["brain_backend"] not in MODES:
            raise ValueError(f"brain_backend must be one of {list(MODES)}")
        out["brain_backend"] = body["brain_backend"]
    if "mac_calls_per_hour" in body:
        v = body["mac_calls_per_hour"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not CALLS_PER_HOUR_MIN <= v <= CALLS_PER_HOUR_MAX:
            raise ValueError(f"mac_calls_per_hour must be {CALLS_PER_HOUR_MIN}-{CALLS_PER_HOUR_MAX}")
        out["mac_calls_per_hour"] = int(v)
    return out


def _read_state(live: Path | None = None) -> dict:
    try:
        d = json.loads((_live(live) / STATE_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(live: Path | None, doc: dict) -> None:
    p = _live(live) / STATE_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp%d" % os.getpid())
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _update(live: Path | None, **fields) -> dict:
    st = _read_state(live)
    st.update(fields)
    _write_state(live, st)
    return st


def binary() -> str | None:
    return shutil.which("claude") or next((p for p in (os.path.expanduser("~/.local/bin/claude"),
                                                       "/opt/homebrew/bin/claude", "/usr/local/bin/claude")
                                           if os.path.exists(p)), None)


def calls_last_hour(live: Path | None = None, now: float | None = None, st: dict | None = None) -> int:
    now = now or time.time()
    st = st if st is not None else _read_state(live)
    return sum(1 for t in st.get("calls") or [] if now - float(t) < 3600.0)


def status(live: Path | None = None, now: float | None = None) -> dict:
    """What the dashboard shows: mode, calls in the last hour against the cap, and why the backend is not usable."""
    now = now or time.time()
    ctl = _control(live)
    st = _read_state(live)
    m, cap, n = mode(live, ctl), calls_per_hour(live, ctl), calls_last_hour(live, now, st)
    until = float(st.get("backoff_until") or 0.0)
    if m == "api":
        state = "off"
    elif binary() is None:
        state = "missing"
    elif until > now:
        state = "backoff"
    elif n >= cap:
        state = "cap"
    else:
        state = "ok"
    return {"mode": m, "state": state, "calls_last_hour": n, "calls_per_hour": cap,
            "backoff_until": until if until > now else None, "backoff_why": st.get("backoff_why") if until > now else None,
            "last_ok": st.get("last_ok"), "last_latency_s": st.get("last_latency_s"),
            "last_error": st.get("last_error"), "last_error_ts": st.get("last_error_ts"),
            "calls_today": st.get("calls_total", 0), "cli_cost_reported_total": round(float(st.get("reported_usd") or 0), 4)}


def available(live: Path | None = None, now: float | None = None) -> bool:
    return status(live, now)["state"] == "ok"


# --------------------------------------------------------------------------- the prompt and the answer
def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            out.append(str(b.get("text") if b.get("text") is not None else b.get("content", "")))
        else:
            out.append(str(b))
    return "\n\n".join(x for x in out if x)


def build_prompt(system, messages: list, tool_schema: dict | None) -> tuple[str, str]:
    """(system text, user prompt): one prompt out of the API-style system blocks and messages."""
    sys_text = _text_of(system)
    parts = []
    many = len(messages or []) > 1
    for m in messages or []:
        t = _text_of(m.get("content") if isinstance(m, dict) else m)
        parts.append((f"[{m.get('role', 'user')}]\n" if many and isinstance(m, dict) else "") + t)
    prompt = "\n\n".join(parts)
    if tool_schema:
        name = tool_schema.get("name") or "answer"
        prompt += (f"\n\nWhere the instructions say to call `{name}`, give its input as your whole answer." + JSON_RULE)
    return sys_text, prompt


def extract_json(text: str) -> dict | None:
    """The first complete JSON object in `text` (code fences and prose around it are tolerated)."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    dec = json.JSONDecoder()
    i = s.find("{")
    while i >= 0:
        try:
            obj, _ = dec.raw_decode(s[i:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        i = s.find("{", i + 1)
    return None


def schema_errors(data, schema: dict | None) -> list[str]:
    """Light validation: an object with the required keys, and enums / basic types on its top-level fields."""
    if not isinstance(data, dict):
        return ["answer is not a JSON object"]
    if not schema:
        return []
    errs = [f"missing '{k}'" for k in schema.get("required") or [] if k not in data]
    types = {"string": str, "object": dict, "array": list, "boolean": bool}
    for k, spec in (schema.get("properties") or {}).items():
        if k not in data or not isinstance(spec, dict) or data[k] is None:
            continue
        t = spec.get("type")
        if t in types and not isinstance(data[k], types[t]):
            errs.append(f"'{k}' is not {t}")
        if spec.get("enum") and data[k] not in spec["enum"]:
            errs.append(f"'{k}' not in {spec['enum']}")
    return errs


def clean_env(env: dict | None = None) -> dict:
    """The environment for the CLI: no API keys, no provider switches, so it uses the subscription login."""
    src = dict(os.environ if env is None else env)
    return {k: v for k, v in src.items()
            if k not in STRIP_ENV_EXACT and not any(k.startswith(p) for p in STRIP_ENV_PREFIX)}


def command(system_text: str, schema: dict | None, effort: str | None, model: str = MODEL) -> list[str]:
    cmd = [binary() or "claude", "-p", "--output-format", "json", "--model", model, "--tools", "",
           "--strict-mcp-config", "--setting-sources", "", "--safe-mode", "--no-session-persistence",
           "--disable-slash-commands"]
    if effort:
        cmd += ["--effort", effort]
    if system_text:
        cmd += ["--system-prompt", system_text]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    return cmd


_cwd: str | None = None


def _empty_cwd() -> str:
    global _cwd
    if _cwd is None or not os.path.isdir(_cwd):
        _cwd = tempfile.mkdtemp(prefix="bazaar-mac-cli-")
    return _cwd


# --------------------------------------------------------------------------- the call
def _acquire(live: Path | None, wait_s: float):
    """One CLI call at a time across processes. Returns the open lock file, or raises CLIError("busy")."""
    p = _live(live) / LOCK_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    f = open(p, "w")
    end = time.time() + max(0.0, wait_s)
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            if time.time() >= end:
                f.close()
                raise CLIError("busy", "another Mac call is running") from None
            time.sleep(0.5)


def _log(rec: dict) -> None:
    try:
        from . import client
        client._log(rec)
    except Exception:  # noqa: BLE001 - logging must never break a decision
        pass


def ask_cli(system, messages: list, tool_schema: dict | None = None, timeout: float = TIMEOUT_S, *,
            purpose: str = "", effort: str | None = "medium", live: Path | None = None,
            runner: Callable | None = None, now: Callable[[], float] = time.time, wait_s: float = 0.0):
    """One tool-less call to the Claude Code CLI. Returns an LLMResult (model "claude-cli", key "MAC", cost 0)
    whose single tool call carries the JSON answer; raises CLIError."""
    from .client import LLMResult
    run = runner or subprocess.run
    name = (tool_schema or {}).get("name") or "answer"
    schema = (tool_schema or {}).get("input_schema") or (tool_schema or {}).get("schema")
    t_start = now()
    st = _read_state(live)
    if float(st.get("backoff_until") or 0.0) > t_start:
        raise CLIError("limit", "backing off: " + str(st.get("backoff_why") or ""))
    if calls_last_hour(live, t_start, st) >= calls_per_hour(live):
        raise CLIError("cap", "hourly cap of Mac calls reached")
    if runner is None and binary() is None:
        raise CLIError("error", "claude CLI not found")
    sys_text, prompt = build_prompt(system, messages, tool_schema)
    lock = _acquire(live, wait_s)
    t0 = now()
    try:
        st = _read_state(live)                       # count the call before running it: a crash still counts
        calls = [t for t in st.get("calls") or [] if t0 - float(t) < 3600.0] + [t0]
        _update(live, calls=calls, calls_total=int(st.get("calls_total") or 0) + 1)
        try:
            proc = run(command(sys_text, schema, effort), input=prompt, capture_output=True, text=True,
                       timeout=timeout, env=clean_env(), cwd=_empty_cwd())
        except subprocess.TimeoutExpired:
            _fail(live, purpose, "timeout", f"no answer in {timeout:.0f} s", now() - t0, BACKOFF_FAIL_S, now())
            raise CLIError("timeout", f"no answer in {timeout:.0f} s") from None
        except OSError as e:
            _fail(live, purpose, "error", str(e), now() - t0, BACKOFF_FAIL_S, now())
            raise CLIError("error", str(e)) from None
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except OSError:
            pass
    latency = now() - t0
    out, err = getattr(proc, "stdout", "") or "", getattr(proc, "stderr", "") or ""
    try:
        doc = json.loads(out)
        if not isinstance(doc, dict):
            raise ValueError("not an object")
    except ValueError:
        doc = None
    blob = (out[-600:] + " " + err[-600:]).lower()
    failed = doc is None or doc.get("is_error") or getattr(proc, "returncode", 0) != 0
    if failed:
        msg = str((doc or {}).get("result") or err or out)[:240]
        if any(w in blob for w in LIMIT_WORDS):
            _fail(live, purpose, "limit", msg, latency, BACKOFF_LIMIT_S, now())
            raise CLIError("limit", msg)
        _fail(live, purpose, "error", msg, latency, 0.0, now())
        raise CLIError("error", msg)
    text = str(doc.get("result") or "")
    data = doc.get("structured_output") if isinstance(doc.get("structured_output"), dict) else extract_json(text)
    errs = schema_errors(data, schema)
    reported = float(doc.get("total_cost_usd") or 0.0)
    usage = {k: int((doc.get("usage") or {}).get(k) or 0) for k in
             ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    stop = str(doc.get("stop_reason") or "")
    if errs:
        streak = int(_read_state(live).get("invalid_streak") or 0) + 1
        _fail(live, purpose, "invalid", "; ".join(errs)[:200], latency, BACKOFF_FAIL_S if streak >= 2 else 0.0, now(),
              invalid_streak=streak, reported=reported)
        raise CLIError("invalid", "; ".join(errs))
    st = _read_state(live)
    _update(live, last_ok=now(), last_latency_s=round(latency, 1), invalid_streak=0,
            reported_usd=float(st.get("reported_usd") or 0.0) + reported)
    _log({"purpose": purpose, "model": MODEL_LABEL, "key": KEY_LABEL, "attempt": 0, "latency_s": round(latency, 3),
          "usage": usage, "cost_usd": 0.0, "cli_cost_reported": round(reported, 6), "stop": stop,
          "cli_model": next(iter(doc.get("modelUsage") or {}), ""), "prompt": prompt[-400:],
          "text": text[:600], "tools": [name]})
    return LLMResult(text, [{"id": "mac", "name": name, "input": data}], MODEL_LABEL, KEY_LABEL, usage, 0.0,
                     latency, "max_tokens" if stop == "max_tokens" else (stop or "end_turn"),
                     {"cli_cost_reported": reported, "backend": "mac"})


def _fail(live, purpose: str, kind: str, msg: str, latency: float, backoff_s: float, now: float, **extra) -> None:
    fields: dict[str, Any] = {"last_error": f"{kind}: {msg}"[:240], "last_error_ts": now}
    if "invalid_streak" in extra:
        fields["invalid_streak"] = extra["invalid_streak"]
    if extra.get("reported"):
        fields["reported_usd"] = float(_read_state(live).get("reported_usd") or 0.0) + float(extra["reported"])
    if backoff_s > 0:
        fields.update(backoff_until=now + backoff_s, backoff_why=f"{kind}: {msg}"[:160])
        if kind != "invalid":
            fields["invalid_streak"] = 0
    _update(live, **fields)
    _log({"purpose": purpose, "model": MODEL_LABEL, "key": KEY_LABEL, "attempt": 0, "latency_s": round(latency, 3),
          "error": f"CLIError: {kind}: {msg}"[:240], "error_kind": "mac_" + kind, "cost_usd": 0.0})


# --------------------------------------------------------------------------- routing (called from client.ask)
MAC_PURPOSES = {"strategy", "brain_eval"}        # the brain's council votes ask with mac=True


def route(*, purpose: str, system, messages: list, tools: list | None, deadline: float | None,
          effort: str | None, mac: bool = False, live: Path | None = None):
    """Try the Mac backend for a brain call. Returns an LLMResult, or None to use the API.
    In "mac" mode a failure raises LLMUnavailable instead (the brain then keeps its last plan)."""
    if not (mac or purpose in MAC_PURPOSES) or not tools or len(tools) != 1:
        return None
    m = mode(live)
    if m == "api":
        return None
    from .router import LLMUnavailable
    last = None
    for attempt in range(2):                         # an invalid answer is asked once more, then the API
        remaining = None if deadline is None else deadline - time.time()
        timeout = TIMEOUT_S if remaining is None else min(TIMEOUT_S, remaining - 2.0)
        if timeout < 20.0:
            last = CLIError("timeout", "not enough time left before the deadline")
            break
        try:
            return ask_cli(system, messages, tools[0], timeout, purpose=purpose, effort=effort or "medium",
                           live=live, wait_s=min(60.0, max(0.0, timeout - 20.0)))
        except CLIError as e:
            last = e
            if e.kind != "invalid":
                break
    if m == "mac":
        raise LLMUnavailable(f"{purpose}: Mac backend: {last}")
    return None
