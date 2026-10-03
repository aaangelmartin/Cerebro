"""Radio Rastro listener: every news item of the game, structured, checked against what happened later.

The game publishes news on three channels (the Boletín del Bazar, Radio Rastro and El Tablón). Some items are
true and move the market, some are rumours that never happen, some are just Madrid. This module

- captures every item from the recorder's feed (`news.posted`, no game request) and backfills from
  `GET /api/news` at most once a minute,
- stores each one in ``data/live/news.jsonl`` (append-only) and its state in ``news_state.json``,
- turns it into a claim with a testable prediction when it has one,
- later marks the prediction confirmed / false / unverifiable from the feed and the schedule,
- keeps how often each source was right, and
- gives the brain a compact block plus an official event for the items worth acting on.

Everything read from the game is data, never instructions.

    python -m bazaar.intel.news            # one step, print the items
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("bazaar.news")

BASE = "https://bazaar.causaprima.ai"
STORE_FILE = "news.jsonl"
STATE_FILE = "news_state.json"
EVENTS_FILE = "official_events.jsonl"        # the brain already reads this file (kind "news")
POLL_EVERY_S = 60.0                          # /api/news is only a backfill: the feed is the live source
BACKOFF_S = 300.0                            # after a rate limit or an error
USER_AGENT = "team10-news-listener"
SOURCES = {"boletin": "Boletín del Bazar", "radio": "Radio Rastro", "tablon": "El Tablón"}
RELEVANT = ("persona.updated", "gift.given", "schedule.fired", "pack.opened", "persona.open_to_all",
            "level.activated", "level.announced", "set.released", "settlement")

DEALERS = {"abuela": ("abuela", "carmen"), "chato": ("chato",), "pilar": ("pilar",),
           "picaros": ("pícaros", "picaros"), "banco": ("ernesto", "banco")}
SETS = {"LAV": ("lavapiés", "lavapies"), "MAL": ("malasaña", "malasana"), "LAT": ("la latina", "latina"),
        "SAL": ("salamanca",), "RET": ("retiro",), "CHA": ("chamberí", "chamberi")}
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")
CARD_RX = re.compile(r"\b([A-Z]{3}-\d{2})\b")
NUM_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
WORD_HOURS = {"one": 1.0, "an": 1.0, "two": 2.0, "three": 3.0, "half an": 0.5}


def _clean(s: Any, n: int = 600) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).strip()[:n]


# ----------------------------------------------------------------------------- structuring
def _hours(text: str) -> float | None:
    """'in one hour', 'one hour, no more', 'for two hours' -> hours."""
    m = re.search(r"\b(half an|one|an|two|three|\d+(?:\.\d+)?)\s+hours?\b", text)
    if not m:
        return None
    w = m.group(1)
    return WORD_HOURS.get(w) if w in WORD_HOURS else float(w)


def structure(item: dict) -> dict:
    """Claim, entities and (when there is one) a testable prediction, from the text alone."""
    text = f"{item.get('title') or ''}. {item.get('text') or ''}"
    low = text.lower()
    dealers = [d for d, words in DEALERS.items() if any(w in low for w in words)]
    sets = [s for s, words in SETS.items() if any(w in low for w in words)]
    rar = [r for r in RARITIES if re.search(rf"\b{r}s?\b", low)]
    cards = CARD_RX.findall(text)
    pct = [float(x.replace(",", ".")) for x in NUM_RX.findall(text)]
    hours = _hours(low)
    ent = {"dealers": dealers, "sets": sets, "rarities": rar, "cards": cards, "percents": pct, "hours": hours}
    at = float(item.get("t_hours") or 0.0)
    pred = None
    kind = "flavour"
    gives = re.search(r"\bgiv(?:es|ing|e)\b|\bhands? out\b|\bfree\b|\bgift", low)
    seeks = re.search(r"\blooking for\b|\bseeks?\b|\bwants?\b|\bpays? (?:above|over|more|extra|double)\b|\bbuys?\b", low)
    cheaper = re.search(r"\bcheaper\b|\bdiscount|\bsale\b|\bhalf price\b|\bsells? .* (?:below|under)\b", low)
    if dealers and gives:
        what = "legendary" if "legendary" in low else "epic" if "epic" in low else "pack" if "pack" in low else "card"
        everyone = bool(re.search(r"every team|everyone|anyone|all teams|each team", low))
        kind = "gift"
        delay = hours if hours is not None and re.search(r"\bin (?:one|an|two|three|\d)", low) else 0.0
        pred = {"kind": "gift", "dealer": dealers[0], "what": what, "everyone": everyone,
                "from_hours": round(at + (delay or 0.0), 3), "deadline_hours": round(at + (delay or 0.0) + 1.5, 3),
                "cheap_test": bool(re.search(r"says? hello|asks?|greet", low))}
    elif dealers and (seeks or cheaper):
        kind = "dealer_change"
        pred = {"kind": "dealer_change", "dealer": dealers[0], "direction": "pays_more" if seeks else "sells_cheaper",
                "sets": sets, "rarities": rar, "window_hours": hours,
                "from_hours": at, "deadline_hours": round(at + 1.5, 3), "cheap_test": True}
    elif (sets or cards) and re.search(r"fever|rush|craze|shortage|scarce|flood|arriv|releas|new set", low):
        kind = "market_event"
        pred = {"kind": "schedule", "sets": sets, "cards": cards, "from_hours": at,
                "deadline_hours": round(at + (hours or 2.0) + 1.0, 3), "cheap_test": False}
    elif dealers or sets or cards:
        kind = "mention"
    return {"claim": kind, "entities": ent, "prediction": pred}


# ----------------------------------------------------------------------------- items
def item_from_payload(p: dict, ts: float | None = None, tick: Any = None, t_hours: Any = None) -> dict | None:
    if not isinstance(p, dict) or p.get("id") is None:
        return None
    src = str(p.get("source") or "").lower()
    it = {"id": int(p["id"]), "ts": round(float(ts or time.time()), 3),
          "tick": p.get("tick") if p.get("tick") is not None else tick,
          "t_hours": p.get("at_hours") if p.get("at_hours") is not None else t_hours,
          "source": src if src in SOURCES else (src or "unknown"),
          "source_name": _clean(p.get("source_name") or SOURCES.get(src) or src, 60),
          "title": _clean(p.get("headline") or p.get("title") or p.get("text"), 200),
          "text": _clean(p.get("body"), 800), "raw": p}
    return it


def _fetch_news(url: str, etag: str | None) -> tuple[int, str | None, list[dict]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **({"If-None-Match": etag} if etag else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read().decode("utf-8"))
            return r.status, r.headers.get("ETag"), list(body.get("news") or [])
    except urllib.error.HTTPError as e:
        return e.code, etag, []


# ----------------------------------------------------------------------------- the listener
class Listener:
    """`fetch(url, etag) -> (status, etag, news list)` can be replaced in tests; pass fetch=False for no polling."""

    def __init__(self, live: Path | str | None = None, record: Path | str | None = None,
                 fetch: Callable | bool | None = None, now: Callable[[], float] = time.time,
                 poll_every: float = POLL_EVERY_S):
        if live is None or record is None:
            from bazaar import config
            live = live or config.LIVE
            record = record or (config.DATA / "record")
        self.live, self.record = Path(live), Path(record)
        self.live.mkdir(parents=True, exist_ok=True)
        self.fetch = _fetch_news if fetch is None else fetch
        self.now = now
        self.poll_every = poll_every
        self.state = self._load()
        self.items: dict[str, dict] = self.state.setdefault("items", {})
        self._pos: dict[str, int] = {}           # feed file -> bytes read (in memory: one full read per start)
        self.rows: list[dict] = []               # feed rows the verification looks at
        self._row_ids: set = set()
        self._next_poll = 0.0
        self._etag: str | None = None

    # --- storage
    def _load(self) -> dict:
        try:
            return json.loads((self.live / STATE_FILE).read_text())
        except (OSError, ValueError):
            return {"items": {}}

    def _save(self) -> None:
        self.state["updated"] = self.now()
        self.state["sources"] = reliability(self.items)
        tmp = self.live / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False))
        tmp.replace(self.live / STATE_FILE)

    def _add(self, it: dict | None, via: str) -> bool:
        if not it:
            return False
        key = str(it["id"])
        if key in self.items:
            old = self.items[key]                       # the API knows the game hour; the feed knows the wall time
            for f in ("tick", "t_hours"):
                if old.get(f) is None and it.get(f) is not None:
                    old[f] = it[f]
            return False
        st = structure(it)
        rec = {**it, **st, "via": via, "status": "open" if st["prediction"] else "flavour",
               "evidence": None, "checked_at": None}
        self.items[key] = rec
        with open(self.live / STORE_FILE, "a") as fh:
            fh.write(json.dumps({k: rec[k] for k in ("id", "ts", "tick", "t_hours", "source", "source_name",
                                                     "title", "text", "raw")}, ensure_ascii=False) + "\n")
        return True

    # --- intake
    def _read_feed(self) -> list[dict]:
        """New rows of every feed file (a day per file). The first call reads the whole day."""
        out = []
        for path in sorted((self.record / "feed").glob("*.jsonl")):
            pos = self._pos.get(path.name, 0)
            try:
                size = path.stat().st_size
                if size < pos:
                    pos = 0
                if size == pos:
                    continue
                with open(path, "rb") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
            except OSError:
                continue
            end = chunk.rfind(b"\n") + 1                # keep a half-written last line for the next call
            self._pos[path.name] = pos + end
            for line in chunk[:end].splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    def ingest_feed(self) -> list[dict]:
        new = []
        for r in self._read_feed():
            t = r.get("type")
            if t == "news.posted":
                it = item_from_payload(r.get("payload") or {}, ts=r.get("seen_at") or r.get("ts"),
                                       tick=r.get("tick"), t_hours=r.get("t"))
                if self._add(it, "feed"):
                    new.append(self.items[str(it["id"])])
            elif t in RELEVANT:
                rid = r.get("id") if r.get("id") is not None else r.get("seq")
                if rid in self._row_ids:
                    continue
                self._row_ids.add(rid)
                if t == "settlement" and not (r.get("payload") or {}).get("persona"):
                    continue                             # only dealer settlements matter here
                self.rows.append({"id": rid, "type": t, "tick": r.get("tick"), "t": r.get("t"),
                                  "actor": r.get("actor"), "payload": r.get("payload") or {}})
        return new

    def poll(self) -> list[dict]:
        """Backfill from GET /api/news, at most once per `poll_every` seconds; backs off after an error."""
        now = self.now()
        if not self.fetch or now < self._next_poll:
            return []
        self._next_poll = now + self.poll_every
        try:
            status, etag, news = self.fetch(BASE + "/api/news", self._etag)
        except Exception as e:  # noqa: BLE001 - the feed still works
            log.warning("news poll failed: %s", e)
            self._next_poll = now + BACKOFF_S
            return []
        if status == 304:
            return []
        if status != 200:
            self._next_poll = now + BACKOFF_S
            return []
        self._etag = etag
        new = []
        for n in sorted(news, key=lambda x: x.get("id") or 0):
            it = item_from_payload(n, ts=now)
            if self._add(it, "api"):
                new.append(self.items[str(it["id"])])
        return new

    # --- verification
    def _hours_now(self) -> float | None:
        try:
            return float(json.loads((self.record / "latest" / "clock.json").read_text()).get("t_hours"))
        except (OSError, ValueError, TypeError):
            return max((float(r["t"]) for r in self.rows if r.get("t") is not None), default=None)

    def _schedule_notes(self) -> list[str]:
        try:
            d = json.loads((self.record / "latest" / "schedule.json").read_text())
            return [str(u.get("note") or "") + " " + str(u.get("action") or "") for u in d.get("upcoming") or []]
        except (OSError, ValueError):
            return []

    def verify(self) -> list[dict]:
        """Check every open prediction; returns the items whose status changed."""
        t_now = self._hours_now()
        used = set(self.state.setdefault("used_rows", []))
        changed = []
        for it in sorted(self.items.values(), key=lambda x: x["id"]):
            p = it.get("prediction")
            if it.get("status") != "open" or not p:
                continue
            t0 = float(p.get("from_hours") or it.get("t_hours") or 0.0)
            posted = float(it.get("t_hours") or 0.0)
            dead = float(p.get("deadline_hours") or (t0 + 1.5))
            verdict = ev = None
            if p["kind"] == "dealer_change":
                # the game changes the dealer (persona.updated by "news") when the rumour is true; the next
                # update of the same dealer is the change ending, so it is consumed with it
                ups = [r for r in self.rows if r["type"] == "persona.updated" and r["id"] not in used
                       and (r["payload"].get("persona") == p["dealer"]) and float(r.get("t") or 0) >= posted - 0.01]
                ups.sort(key=lambda r: float(r.get("t") or 0))
                if ups and float(ups[0]["t"]) <= dead:
                    verdict, ev = "confirmed", f"{p['dealer']} changed at h{ups[0]['t']} (tick {ups[0]['tick']})"
                    used.add(ups[0]["id"])
                    end = [r for r in ups[1:] if float(r["t"]) <= float(ups[0]["t"]) + (p.get("window_hours") or 1.0) + 0.3]
                    if end:
                        used.add(end[0]["id"])
                        ev += f", back at h{end[0]['t']}"
                    it["active_window"] = [float(ups[0]["t"]), float(end[0]["t"]) if end else None]
            elif p["kind"] == "gift":
                gifts = [r for r in self.rows if r["type"] == "gift.given" and r.get("actor") == p["dealer"]
                         and float(r.get("t") or 0) >= posted - 0.01 and float(r.get("t") or 0) <= dead]
                grants = [r for r in self.rows if r["type"] == "schedule.fired" and float(r.get("t") or 0) >= posted - 0.01
                          and float(r.get("t") or 0) <= dead and "grant" in str(r["payload"].get("action"))]

                def has(r):
                    pl = r["payload"]
                    if p["what"] == "pack":
                        return bool(pl.get("packs"))
                    if p["what"] in ("legendary", "epic"):
                        tail = "-12" if p["what"] == "legendary" else "-11"
                        return any(str(c).endswith(tail) for c in pl.get("cards") or [])
                    return bool(pl.get("cards") or pl.get("packs"))
                hits = [r for r in gifts if has(r)]
                teams = {r["payload"].get("team") for r in hits}
                need = 6 if p.get("everyone") and p["what"] in ("pack", "card") else 1
                if len(teams) >= need:
                    verdict, ev = "confirmed", f"{len(teams)} teams got a {p['what']} from {p['dealer']} by h{hits[-1]['t']}"
                elif grants and p["what"] in ("pack", "card"):
                    verdict, ev = "confirmed", f"grant fired at h{grants[0]['t']}: {grants[0]['payload'].get('note')}"
            elif p["kind"] == "schedule":
                words = [w for s in p.get("sets") or [] for w in SETS.get(s, ())]
                notes = [n for n in self._schedule_notes() if any(w in n.lower() for w in words)]
                fired = [r for r in self.rows if r["type"] == "schedule.fired" and float(r.get("t") or 0) >= posted - 0.01
                         and any(w in str(r["payload"].get("note")).lower() for w in words)]
                if notes or fired:
                    verdict, ev = "confirmed", (notes[0] if notes else str(fired[0]["payload"].get("note")))[:160]
            if verdict is None and t_now is not None and t_now > dead:
                verdict = "false" if p["kind"] in ("dealer_change", "gift") else "unverifiable"
                ev = f"nothing seen by h{round(dead, 2)}"
            if verdict:
                it.update(status=verdict, evidence=ev, checked_at=self.now())
                changed.append(it)
        self.state["used_rows"] = sorted(used, key=str)[-200:]
        return changed

    # --- one step
    def step(self) -> dict:
        new = self.ingest_feed() + self.poll()
        changed = self.verify()
        if new or changed:
            self._save()
            rel = reliability(self.items)
            t_now = self._hours_now()
            evs = []                                            # the brain reads these as "official" events
            for it in new:
                fresh = (self.now() - float(it.get("ts") or 0) < 600 and
                         (t_now is None or it.get("t_hours") is None or t_now - float(it["t_hours"]) < 0.25))
                if fresh and actionable(it, rel):               # a backfilled old item never wakes the brain
                    evs.append(_event(it, rel, "posted"))
            for it in changed:
                if it["status"] == "confirmed" and it not in new:
                    evs.append(_event(it, rel, "confirmed"))
            if evs:
                with open(self.live / EVENTS_FILE, "a") as fh:
                    for e in evs:
                        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        return {"new": new, "changed": changed}


def _event(it: dict, rel: dict, what: str) -> dict:
    r = (rel.get(it["source"]) or {}).get("reliability")
    head = f"News {what} ({it.get('source_name')}, reliability {r if r is not None else 'unknown'}): {it['title']}"
    return {"ts": round(time.time(), 3), "kind": "news", "source": "news", "summary": _clean(head, 400),
            "diff_excerpt": _clean((it.get("text") or "") + (f" | {it['evidence']}" if it.get("evidence") else ""), 400),
            "news_id": it["id"], "status": it["status"]}


# ----------------------------------------------------------------------------- reliability and views
def reliability(items: dict[str, dict]) -> dict[str, dict]:
    """Per source: how many predictions were confirmed or false. Laplace-smoothed share right."""
    out: dict[str, dict] = {}
    for it in items.values():
        s = out.setdefault(it.get("source") or "unknown", {"name": it.get("source_name"), "items": 0, "confirmed": 0,
                                                           "false": 0, "open": 0, "unverifiable": 0, "flavour": 0})
        s["items"] += 1
        s[it.get("status") if it.get("status") in s else "flavour"] += 1
    for s in out.values():
        n = s["confirmed"] + s["false"]
        s["reliability"] = round((s["confirmed"] + 1) / (n + 2), 2) if n else None
    return out


def actionable(it: dict, rel: dict | None = None) -> bool:
    """Worth waking the brain: it predicts something, and the source has been right or the test is cheap."""
    p = it.get("prediction")
    if not p or it.get("status") in ("false", "unverifiable", "flavour"):
        return False
    r = ((rel or {}).get(it.get("source")) or {}).get("reliability")
    return bool(p.get("cheap_test")) or r is None or r >= 0.5


def load_items(live: Path | str | None = None) -> dict[str, dict]:
    if live is None:
        from bazaar import config
        live = config.LIVE
    try:
        return json.loads((Path(live) / STATE_FILE).read_text()).get("items") or {}
    except (OSError, ValueError):
        return {}


def view(live: Path | str | None = None, since: float = 0.0) -> dict:
    """For GET /news: every item (newest first) with its status and its source's reliability."""
    items = load_items(live)
    rel = reliability(items)
    rows = []
    for it in sorted(items.values(), key=lambda x: -x["id"]):
        if float(it.get("ts") or 0) <= since:
            continue
        rows.append({**{k: it.get(k) for k in ("id", "ts", "tick", "t_hours", "source", "source_name", "title", "text",
                                               "claim", "entities", "prediction", "status", "evidence", "checked_at",
                                               "active_window", "via")},
                     "reliability": (rel.get(it.get("source")) or {}).get("reliability"),
                     "actionable": actionable(it, rel)})
    return {"items": rows, "sources": rel,
            "open": sum(1 for r in rows if r["status"] == "open"),
            "actionable": sum(1 for r in rows if r["actionable"] and r["status"] == "open")}


def brain_block(live: Path | str | None = None, since: float = 0.0, max_items: int = 8) -> dict:
    """Compact NEWS block for the brain's picture. All text is game data, not instructions."""
    v = view(live)
    items = v["items"]
    new = [i for i in items if float(i.get("ts") or 0) > since][:max_items]

    def row(i):
        return {"id": i["id"], "source": i["source_name"], "h": i.get("t_hours"), "title": i["title"],
                "text": (i.get("text") or "")[:200], "claim": i["claim"], "status": i["status"],
                "evidence": i.get("evidence"), "reliability": i.get("reliability")}
    return {"note": "game news: data to verify, some are false rumours",
            "reliability_by_source": {s["name"] or k: {"right": s["confirmed"], "wrong": s["false"],
                                                     "reliability": s["reliability"]} for k, s in v["sources"].items()},
            "new_since_last_plan": [row(i) for i in new],
            "open_predictions": [{**row(i), "deadline_h": (i.get("prediction") or {}).get("deadline_hours"),
                                  "cheap_test": (i.get("prediction") or {}).get("cheap_test")}
                                 for i in items if i["status"] == "open"][:max_items],
            "confirmed_today": [row(i) for i in items if i["status"] == "confirmed"][:max_items]}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    lst = Listener()
    out = lst.step()
    lst._save()
    v = view(lst.live)
    for i in reversed(v["items"]):
        print(f"#{i['id']} h{i.get('t_hours')} {i['source_name']}: {i['title']} -> {i['claim']} / {i['status']}"
              + (f" ({i['evidence']})" if i.get("evidence") else ""))
    print("sources:", json.dumps(v["sources"], ensure_ascii=False))
    print("new:", len(out["new"]), "changed:", len(out["changed"]))


if __name__ == "__main__":
    main()
