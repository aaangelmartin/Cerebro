"""What the public book says about rival teams' affinities.

Every team has the same six set multipliers (1.6, 1.3, 1.1, 0.9, 0.7, 0.5), shuffled. A team that bids
cash for a card of a set (`give: cash, want: card`) at a price near or above book shows it values that
set; a team that keeps selling a set's cards cheaply shows it does not. The feed (`offer.listed`) names
the real team behind each offer, while the venue books only show pseudonyms, so we map offer id -> team
from the feed.

Seeded with Friday (seed lesson L16): t18 bids 62 on LAT rares, t17 70 and t08 50-53 on MAL-09,
t08 60-62 on SAL-09/SAL-10, t14 55 for LAV-07.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from pathlib import Path

BOOK = {"common": 10, "uncommon": 25, "rare": 70, "epic": 180, "legendary": 450}
FRIDAY_BIDS = [("t18", "LAT", 62 / 70), ("t18", "LAT", 62 / 70), ("t17", "MAL", 70 / 70), ("t08", "MAL", 52 / 70),
               ("t08", "SAL", 61 / 70), ("t08", "SAL", 60 / 70), ("t14", "LAV", 55 / 25)]
MAX_SAMPLES = 30


def _set(ref: str) -> str:
    return str(ref).split("-")[0]


def _rarity_of(ref: str, catalog_rarity: dict[str, str] | None) -> str:
    if catalog_rarity and ref in catalog_rarity:
        return catalog_rarity[ref]
    try:
        n = int(str(ref).split("-")[1])
    except (IndexError, ValueError):
        return "common"
    return "common" if n <= 5 else "uncommon" if n <= 8 else "rare" if n <= 10 else "epic" if n == 11 else "legendary"


class RivalModel:
    def __init__(self, path: Path | None = None, seed: bool = True):
        if path is None:
            from bazaar import config
            path = config.LIVE / "rivals.json"
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data: dict = {"bids": {}, "asks": {}, "offer_team": {}, "deals": []}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except (OSError, ValueError):
                pass
        if seed and not self.data["bids"]:
            for team, s, r in FRIDAY_BIDS:
                self.data["bids"].setdefault(team, {}).setdefault(s, []).append(round(r, 3))

    def save(self) -> None:
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, default=str))
                tmp.replace(self.path)
            except OSError:
                pass

    # --- evidence ------------------------------------------------------------------
    def ingest_feed(self, events: list[dict], my_id: str | None, catalog_rarity: dict[str, str] | None = None) -> None:
        changed = False
        with self.lock:
            for e in events or []:
                if e.get("type") != "offer.listed":
                    continue
                team = e.get("actor") or ""
                o = ((e.get("payload") or {}).get("offer")) or {}
                if not team or team == my_id or not team.startswith("t") or not o.get("id"):
                    continue
                self.data["offer_team"][str(o["id"])] = team
                self._learn_offer(team, o, catalog_rarity)
                changed = True
            if len(self.data["offer_team"]) > 3000:
                keep = sorted(self.data["offer_team"], key=lambda k: int(k))[-2000:]
                self.data["offer_team"] = {k: self.data["offer_team"][k] for k in keep}
        if changed:
            self.save()

    def _learn_offer(self, team: str, o: dict, catalog_rarity: dict[str, str] | None) -> None:
        give, want = o.get("give") or {}, o.get("want") or {}
        want_refs = list(want.get("cards") or []) + [t[5:] for t in want.get("types") or [] if str(t).startswith("card:")]
        give_refs = [a.get("ref") for a in give.get("assets") or [] if isinstance(a, dict) and a.get("ref")]
        cash_in, cash_out = int(give.get("cash") or 0), int(want.get("cash") or 0)
        if want_refs and cash_in and not give_refs:            # a bid: they pay cash for a card
            per = cash_in / len(want_refs)
            for ref in want_refs:
                self._add("bids", team, _set(ref), per / BOOK[_rarity_of(ref, catalog_rarity)])
        if give_refs and cash_out and not want_refs:           # an ask: they sell a card
            per = cash_out / len(give_refs)
            for ref in give_refs:
                self._add("asks", team, _set(ref), per / BOOK[_rarity_of(ref, catalog_rarity)])

    def _add(self, key: str, team: str, s: str, ratio: float) -> None:
        xs = self.data[key].setdefault(team, {}).setdefault(s, [])
        xs.append(round(ratio, 3))
        del xs[:-MAX_SAMPLES]

    def team_of(self, offer: dict) -> str | None:
        t = self.data["offer_team"].get(str(offer.get("id")))
        if t:
            return t
        m = str(offer.get("maker") or "")
        return m if m.startswith("t") and m[1:].isdigit() else None

    # --- reading ---------------------------------------------------------------------
    def interest(self, team: str, s: str) -> float:
        """0..1: how strongly this team's offers say it values set `s` (bids up, cheap asks down)."""
        bids = (self.data["bids"].get(team) or {}).get(s) or []
        asks = (self.data["asks"].get(team) or {}).get(s) or []
        score = 0.0
        if bids:
            score += min(1.0, statistics.median(bids)) * min(1.0, 0.5 + 0.25 * len(bids))
        if asks:
            score -= 0.3 * min(1.0, 0.5 + 0.25 * len(asks))
        return max(0.0, min(1.0, score))

    def fans(self, s: str, exclude: set[str] | None = None, min_interest: float = 0.4) -> list[tuple[str, float]]:
        """Teams that bid for set `s`, strongest first."""
        out = [(t, self.interest(t, s)) for t in self.data["bids"] if t not in (exclude or set())]
        return sorted([x for x in out if x[1] >= min_interest], key=lambda x: -x[1])

    def bid_level(self, team: str, s: str) -> float | None:
        """The team's typical bid for set `s` as a share of book."""
        bids = (self.data["bids"].get(team) or {}).get(s) or []
        return float(statistics.median(bids)) if bids else None

    # --- fair play -----------------------------------------------------------------------
    def record_deal(self, team: str) -> None:
        with self.lock:
            self.data["deals"].append([time.time(), team])
            self.data["deals"] = [d for d in self.data["deals"] if time.time() - d[0] < 7200]
            self.save()

    def deals_last_hour(self, team: str) -> int:
        now = time.time()
        return sum(1 for at, t in self.data["deals"] if t == team and now - at < 3600)

    def summary(self, sets: list[str]) -> dict:
        return {s: [t for t, _ in self.fans(s)[:4]] for s in sets}
