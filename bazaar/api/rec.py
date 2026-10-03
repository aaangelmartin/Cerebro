"""Read-only views over the recorder's files (data/record) and the bell notifications, for the dashboard API.

Nothing here writes anywhere: it only reads files the recorder, the bot, the broker and the lab write.

    latest(record, "me" | "books/v03" | "dealers/abuela")   -> latest/<name>.json
    stream(record, "feed", since_seq=, limit=, tail=)        -> {"rows", "last_seq", "stream_last_seq", "more"}
    duels(record) / duel(record, id)                         -> headers / full transcript
    threads(record) / thread(record, id)
    notifications(live, lab, record, since)                  -> {"items": [{id, ts, type, title, text, href}], "now"}
"""
from __future__ import annotations

import bisect
import json
import re
import threading
import time
from pathlib import Path

NAME_RX = re.compile(r"[A-Za-z0-9_\-]+")
LATEST_ROOT = {"clock", "me", "my_offers", "leaderboard", "venues", "catalog", "dealers", "levels", "schedule", "cards"}
LATEST_DIRS = {"books", "dealers"}
STREAMS = {"feed", "leaderboard", "books", "book_snapshots", "me", "my_offers", "threads", "duels", "cards", "gaps",
           "venues", "clock", "catalog", "dealers", "levels", "schedule"}
DAY_RX = re.compile(r"\d{4}-\d{2}-\d{2}\.jsonl")
SEQ_RX = re.compile(rb'"seq"\s*:\s*(\d+)')


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# --------------------------------------------------------------------------- latest
def latest(record: Path, name: str):
    """latest/<name>.json; None when unknown or missing (the caller answers 404)."""
    parts = name.strip("/").split("/")
    if not all(NAME_RX.fullmatch(p) for p in parts):
        return None
    if len(parts) == 1 and parts[0] in LATEST_ROOT:
        path = record / "latest" / f"{parts[0]}.json"
    elif len(parts) == 2 and parts[0] in LATEST_DIRS:
        path = record / "latest" / parts[0] / f"{parts[1]}.json"
    elif len(parts) == 1 and parts[0] == "books":   # all books at once: {venue: book}
        out = {}
        for p in sorted((record / "latest" / "books").glob("*.json")):
            b = _read_json(p)
            if b is not None:
                out[p.stem] = b
        return out
    else:
        return None
    return _read_json(path)


# --------------------------------------------------------------------------- streams (indexed by seq)
class _FileIndex:
    """Byte offset of every complete line of one append-only JSONL file, with its seq. Grows incrementally."""

    def __init__(self, path: Path):
        self.path = path
        self.size = 0          # bytes indexed (always at a line boundary)
        self.seqs: list[int] = []
        self.offs: list[int] = []
        self.ends: list[int] = []

    def update(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.size:   # truncated or replaced: start over
            self.size, self.seqs, self.offs, self.ends = 0, [], [], []
        if size == self.size:
            return
        with self.path.open("rb") as f:
            f.seek(self.size)
            chunk = f.read(size - self.size)
        pos = 0
        base = self.size
        last_seq = self.seqs[-1] if self.seqs else -1
        while True:
            nl = chunk.find(b"\n", pos)
            if nl < 0:
                break
            line = chunk[pos:nl]
            m = SEQ_RX.search(line, 0, 64) or SEQ_RX.search(line)
            if m:
                seq = int(m.group(1))
                if seq < last_seq:   # never expected; keep the index sorted anyway
                    seq = last_seq
                self.seqs.append(seq)
                self.offs.append(base + pos)
                self.ends.append(base + nl)
                last_seq = seq
            pos = nl + 1
        self.size = base + pos

    def read(self, i0: int, i1: int) -> list[dict]:
        if i1 <= i0:
            return []
        rows = []
        with self.path.open("rb") as f:
            f.seek(self.offs[i0])
            data = f.read(self.ends[i1 - 1] - self.offs[i0])
        for line in data.split(b"\n"):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows


_indexes: dict[str, _FileIndex] = {}
_index_lock = threading.Lock()


def _stream_files(record: Path, name: str) -> list[_FileIndex]:
    d = record / name
    try:
        files = sorted(p for p in d.iterdir() if DAY_RX.fullmatch(p.name))
    except OSError:
        return []
    out = []
    with _index_lock:
        for p in files:
            key = str(p)
            ix = _indexes.get(key)
            if ix is None:
                ix = _indexes[key] = _FileIndex(p)
            ix.update()
            out.append(ix)
    return out


def stream(record: Path, name: str, since_seq: int | None = None, limit: int = 500, tail: int | None = None):
    if name not in STREAMS:
        return None
    files = _stream_files(record, name)
    stream_last = next((ix.seqs[-1] for ix in reversed(files) if ix.seqs), None)
    rows: list[dict] = []
    if tail:
        # The last `tail` rows (after since_seq if given), oldest first.
        need = min(tail, limit)
        chunks = []
        for ix in reversed(files):
            if need <= 0:
                break
            i1 = len(ix.seqs)
            i0 = max(0, i1 - need)
            if since_seq is not None:
                i0 = max(i0, bisect.bisect_right(ix.seqs, since_seq))
            if i1 > i0:
                chunks.append(ix.read(i0, i1))
                need -= i1 - i0
            if since_seq is not None and ix.seqs and ix.seqs[0] <= since_seq:
                break
        for c in reversed(chunks):
            rows.extend(c)
        more = False
    else:
        start = -1 if since_seq is None else since_seq
        need = limit
        more = False
        for ix in files:
            if not ix.seqs or ix.seqs[-1] <= start:
                continue
            i0 = bisect.bisect_right(ix.seqs, start)
            i1 = min(len(ix.seqs), i0 + need)
            rows.extend(ix.read(i0, i1))
            need -= i1 - i0
            if need <= 0:
                more = i1 < len(ix.seqs) or ix is not files[-1]
                break
    last = rows[-1].get("seq") if rows else since_seq
    return {"stream": name, "rows": rows, "last_seq": last, "stream_last_seq": stream_last, "more": more}


# --------------------------------------------------------------------------- duels / threads
_header_cache: dict[str, tuple[float, int, dict]] = {}


def _headers(d: Path, drop=("messages",)) -> list[dict]:
    out = []
    try:
        files = [p for p in d.iterdir() if re.fullmatch(r"\d+\.json", p.name)]
    except OSError:
        return []
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        hit = _header_cache.get(str(p))
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            out.append(hit[2])
            continue
        doc = _read_json(p)
        if not isinstance(doc, dict):
            continue
        msgs = doc.get("messages") or []
        head = {k: v for k, v in doc.items() if k not in drop}
        head["last_message"] = msgs[-1] if isinstance(msgs, list) and msgs else None
        head.setdefault("message_count", len(msgs) if isinstance(msgs, list) else None)
        head["updated"] = st.st_mtime
        _header_cache[str(p)] = (st.st_mtime, st.st_size, head)
        out.append(head)
    return out


def duels(record: Path) -> dict:
    items = _headers(record / "duels")
    items.sort(key=lambda h: int(h.get("duel") or 0), reverse=True)
    return {"items": items}


def duel(record: Path, did: str):
    if not re.fullmatch(r"\d+", did):
        return None
    return _read_json(record / "duels" / f"{did}.json")


def threads(record: Path) -> dict:
    items = _headers(record / "threads")
    items.sort(key=lambda h: int(h.get("id") or 0), reverse=True)
    return {"items": items}


def thread(record: Path, tid: str):
    if not re.fullmatch(r"\d+", tid):
        return None
    return _read_json(record / "threads" / f"{tid}.json")


# --------------------------------------------------------------------------- notifications
_first_seen: dict[str, float] = {}


def _seen(key: str, now: float) -> float:
    return _first_seen.setdefault(key, now)


def _jsonl(path: Path, limit: int = 200) -> list[dict]:
    from .server import _tail
    return _tail(path, None, limit)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


LAB_TITLES = {"lesson_status": "Laboratorio: lección", "hypotheses": "Laboratorio: hipótesis", "seed": "Laboratorio",
              "migration": "Laboratorio: migración"}


def notifications(live: Path, lab: Path, record: Path, since: float | None = None, now: float | None = None) -> dict:
    now = now or time.time()
    items: list[dict] = []

    def add(nid, ts, typ, title, text, href=None):
        ts = _num(ts) or now
        items.append({"id": str(nid), "ts": round(ts, 3), "type": typ, "title": title, "text": (text or "")[:300],
                      "href": href or f"#supervision/{nid}"})

    # Lab notices
    for n in _jsonl(lab / "notices.jsonl", 60):
        add(f"lab-{n.get('id') or n.get('ts')}", n.get("ts"), "lab", LAB_TITLES.get(n.get("kind"), "Laboratorio"),
            n.get("text"), f"#laboratorio/{n['lesson_id']}" if n.get("lesson_id") else "#laboratorio")
    # Alerts journal (optional)
    for a in _jsonl(live / "alerts.jsonl", 60):
        lvl = str(a.get("level") or "warn")
        add(f"alert-{a.get('id') or a.get('ts')}", a.get("ts"), "breaker" if lvl == "bad" else "alerta",
            a.get("title") or ("Alerta" if lvl != "bad" else "Alerta grave"), a.get("text") or a.get("message"))
    # Bot status: errors and breakers
    st = _read_json(live / "status.json", {}) or {}
    for e in st.get("last_errors") or []:
        where = e.get("where") or "bot"
        add(f"err-{where}-{e.get('at')}", e.get("at"), "breaker" if where == "breaker" else "error",
            "Disyuntor" if where == "breaker" else f"Error en {where}", e.get("error"))
    br = st.get("breakers") or {}
    tick = _num(st.get("tick"))
    if br.get("cautious"):
        key = f"brk-cautious-{br.get('cautious_until')}"
        add(key, _seen(key, now), "breaker", "Disyuntor: modo prudente", f"Prudente hasta el tick {br.get('cautious_until')}.")
    if tick is not None and (_num(br.get("flood_until")) or -1) > tick:
        key = f"brk-flood-{br.get('flood_until')}"
        add(key, _seen(key, now), "breaker", "Disyuntor: inundación", f"Frenado hasta el tick {br.get('flood_until')}.")
    for dom, until in (br.get("paused_until") or {}).items():
        if tick is not None and (_num(until) or -1) > tick:
            key = f"brk-pause-{dom}-{until}"
            add(key, _seen(key, now), "breaker", f"Disyuntor de {dom}", f"{dom} en pausa hasta el tick {until}.")
    # Novelty
    for n in _jsonl(live / "novelty.jsonl", 40):
        det = n.get("detail")
        add(f"nov-{n.get('id') or n.get('ts')}", n.get("at") or n.get("ts"), "novedad", f"Novedad: {n.get('kind') or 'juego'}",
            det if isinstance(det, str) else json.dumps(det, ensure_ascii=False, default=str))
    # Pending decisions and big outcomes
    for d in _jsonl(live / "decisions.jsonl", 200):
        v = d.get("verdict") or {}
        if isinstance(v, dict) and (v.get("pending") or v.get("status") == "pending" or v.get("needs_approval")):
            a = d.get("action") or {}
            add(d.get("id"), d.get("ts"), "aprobar", "Pendiente de aprobar", a.get("reason") or a.get("kind"))
    for o in _jsonl(live / "outcomes.jsonl", 300):
        if o.get("status") != "deal":
            continue
        r = o.get("realised") or {}
        pts, price = _num(r.get("points_delta")), _num(r.get("price"))
        if (pts is not None and pts >= 2) or (price is not None and price >= 80):
            bits = []
            if price is not None:
                bits.append(f"{price:g} P")
            if pts is not None:
                bits.append(f"{pts:+.1f} pts")
            add(f"out-{o.get('id')}", o.get("ts"), "gran", "Gran operación",
                f"{o.get('kind') or 'trato'} ({o.get('domain') or ''}) · " + " · ".join(bits))
    # Broker sessions
    bs = _read_json(live / "broker_status.json", {}) or {}
    lr = bs.get("last_result") or {}
    if lr.get("session") is not None:
        key = f"broker-{lr.get('session')}"
        eff, stall = _num(lr.get("est_efficiency")), _num(lr.get("stall_efficiency"))
        text = (f"Eficiencia {eff:.2f}" if eff is not None else "Sesión terminada") + (f" vs puesto gratis {stall:.2f}" if stall is not None else "")
        add(key, _seen(key, now), "broker", f"Market Test {lr.get('session')}", text, "#competicion")
    for e in (bs.get("errors") or [])[-5:]:
        add(f"broker-err-{e.get('t')}", e.get("t"), "error", f"Broker: {e.get('where') or 'error'}", e.get("error"))
    # Duel sessions (start / end) from the recorder
    for s in _duel_sessions(record):
        add(f"duelses-{s['session']}-start", s["start"], "duelo", f"Duelos: empieza la sesión {s['session']}",
            f"{s['count']} duelos", f"#duelos")
        if s.get("end"):
            add(f"duelses-{s['session']}-end", s["end"], "duelo", f"Duelos: termina la sesión {s['session']}",
                f"{s['deals']} acuerdos de {s['count']}", "#duelos")

    if since is not None:
        items = [i for i in items if i["ts"] > since]
    items.sort(key=lambda i: i["ts"], reverse=True)
    return {"items": items[:100], "now": now}


_duel_cache: dict = {"key": None, "value": []}


def _duel_sessions(record: Path) -> list[dict]:
    files = _stream_files(record, "duels")
    key = tuple((str(ix.path), ix.size) for ix in files)
    if key == _duel_cache["key"]:
        return _duel_cache["value"]
    heads = {int(h.get("duel")): h for h in _headers(record / "duels") if h.get("duel") is not None}
    first: dict[int, float] = {}
    done: dict[int, float] = {}
    for ix in files:
        for r in ix.read(0, len(ix.seqs)):
            did = r.get("duel")
            if did is None:
                continue
            did = int(did)
            first.setdefault(did, _num(r.get("ts")) or 0)
            if str(r.get("status") or "") not in ("", "live", "open", "active"):
                done[did] = _num(r.get("ts")) or 0
    sessions: dict = {}
    for did, h in heads.items():
        s = sessions.setdefault(h.get("session"), {"session": h.get("session"), "duels": []})
        s["duels"].append(did)
    out = []
    for sid, s in sessions.items():
        if sid is None:
            continue
        starts = [first[d] for d in s["duels"] if d in first]
        if not starts:
            continue
        live = [d for d in s["duels"] if str(heads[d].get("status")) in ("live", "open", "active")]
        ends = [done[d] for d in s["duels"] if d in done]
        out.append({"session": sid, "start": min(starts), "count": len(s["duels"]),
                    "deals": sum(1 for d in s["duels"] if heads[d].get("status") == "deal"),
                    "end": max(ends) if not live and ends else None})
    _duel_cache.update(key=key, value=out)
    return out
