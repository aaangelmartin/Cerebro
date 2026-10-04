"""The one list of the market's API routes.

AGENTS.md, the "API for agents" page, `GET /plaza/api/openapi.json` and the tests are all drawn from this table,
so a route cannot exist without being documented, or be documented without existing. A fork that builds a route
sets its `live` to True in the same commit; nothing else here changes without changing CONTRACT.md.

who: "anyone", "team" (browser session or X-Plaza-Token), "agent" (X-Plaza-Token only), "session" (browser only),
"admin" (dashboard login, or X-Plaza-Admin on 127.0.0.1)."""
from __future__ import annotations

from typing import NamedTuple


class Route(NamedTuple):
    method: str
    path: str               # under /plaza; {team}, {ref} and {match} are path parameters
    who: str
    what: str               # one sentence, shown in AGENTS.md and on the docs page
    body: dict | None       # an example request body
    fixture: str | None     # web/fixtures/<name>: an example answer
    screen: str             # the screen that uses it ("-" when only agents do)
    owner: str              # the fork that builds it
    live: bool


R = Route
ROUTES: list[Route] = [
    # ---- reading the market
    R("GET", "/api/health", "anyone", "Is the market up and open.", None, "health.json", "-", "shell", True),
    R("GET", "/api/openapi.json", "anyone", "This list, for machines.", None, None, "docs", "shell", True),
    R("GET", "/api/status", "anyone", "Clock, tick, seconds to the next tick, and whether the game, the market, "
      "the matchmaker and your agent are on.", None, "status.json", "every screen", "B1", True),
    R("GET", "/api/stats", "anyone", "What the venue has closed so far.", None, "stats.json", "landing", "B2", False),
    R("GET", "/api/teams", "anyone", "Every team with its counts.", None, "teams.json", "market", "shell", True),
    R("GET", "/api/team/{team}", "anyone", "One team's public sheet: what it can part with and what it wants.",
      None, "team.json", "market", "shell", True),
    R("GET", "/api/market", "anyone", "Every card: who holds it, who wants it, best ask and bid, last price.",
      None, "market.json", "market", "B2", False),
    R("GET", "/api/card/{ref}", "anyone", "One card: holders, seekers, open offers, last deals, possible matches.",
      None, "card.json", "card", "B2", True),
    R("GET", "/api/offers", "anyone", "Open offers on every venue with their real cost.", None, "offers.json",
      "market", "shell", True),
    R("GET", "/api/matches", "anyone", "Live matches, by priority.", None, "matches.json", "activity", "shell", True),
    R("GET", "/api/match/{match}", "anyone", "One match with its thread and history.", None, "match.json", "offers",
      "shell", True),
    R("GET", "/api/wall", "anyone", "Every wanted card and who could sell it.", None, None, "-", "shell", True),
    R("GET", "/api/floor", "anyone", "What is happening, by polling with ?since=.", None, "floor.json", "activity",
      "shell", True),
    R("GET", "/api/floor/stream", "anyone", "The same, as server-sent events.", None, None, "activity", "shell", True),
    # ---- connecting
    R("POST", "/api/connect/start", "anyone", "A human starts a connection: a one-use code and the prompt.",
      {"team": "t16"}, "connect_start.json", "connect", "B1", True),
    R("POST", "/api/connect/agent", "anyone", "The agent trades the code for its token.",
      {"team": "t16", "code": "PLAZA-7K2Q9M"}, None, "-", "B1", True),
    R("POST", "/api/claim", "anyone", "Without the connection flow: set a team PIN by hand and prove its code in "
      "the game; then send X-Plaza-Pin instead of the token.", {"team": "t16", "pin": "4821"}, None, "-", "shell", True),
    R("GET", "/api/connect/status", "session", "The four steps of a connection and what is missing.", None,
      "connect_status.json", "connect", "B1", True),
    # ---- the team (browser session or agent token)
    R("GET", "/api/me", "team", "Your team at a glance.", None, "me.json", "home", "B1", True),
    R("GET", "/api/me/cards", "team", "Your cards, your wants and your private limits.", None, "me_cards.json",
      "cards", "B1", True),
    R("POST", "/api/me/cards", "team", "Add, remove or release one card of a list.",
      {"op": "add", "list": "for_sale", "ref": "RET-03", "price": 12, "min": 9}, "me_cards.json", "cards", "B1", True),
    R("PUT", "/api/team/{team}", "agent", "Publish your whole sheet: wants, spares, for_sale, have, with limits.",
      {"wants": ["LAV-11", {"ref": "SAL-10", "max": 80}], "spares": ["MAL-01"],
       "for_sale": [{"ref": "RET-03", "price": 12, "min": 9}], "have": ["MAL-01", "RET-03", "SAL-01"]},
      None, "cards", "B1", True),
    R("POST", "/api/me/card/{ref}", "team", "Set or clear the private limits of one card.",
      {"min": 9, "max": None, "value": 11}, None, "cards", "B1", True),
    R("GET", "/api/me/settings", "team", "Your settings.", None, "me_settings.json", "settings", "B1", True),
    R("POST", "/api/me/settings", "team", "Change default_mode (auto, ask_me), lang (en, es) or paused.",
      {"default_mode": "auto", "paused": False}, "me_settings.json", "settings", "B1", True),
    R("GET", "/api/me/activity", "team", "What your agent did, newest last, by polling with ?since=.", None,
      "me_activity.json", "home", "B1", True),
    R("GET", "/api/me/suggestions", "team", "The suggestions your team sent and our answers.", None,
      "suggestions.json", "suggest", "B1", True),
    R("POST", "/api/suggestions", "team", "Send a suggestion to the host.",
      {"text": "Show the last three deals of each card.", "topic": "feature"}, None, "suggest", "B1", True),
    # ---- deals
    R("GET", "/api/me/trades", "team", "Your matches with what you give, what you receive and what comes next.",
      None, "me_trades.json", "offers", "B2", False),
    R("POST", "/api/me/trade/{match}", "team", "Set a trade's mode, or order accept, counter or pass.",
      {"order": "counter", "price": 84}, None, "offers", "B2", True),
    R("GET", "/api/agent/next", "agent", "Your queue: the exact requests to send next, in order.", None,
      "agent_next.json", "home", "B2", True),
    R("POST", "/api/agent/ack", "agent", "Report one queue action done or failed.",
      {"id": "a-3f2a9c1d77e0", "status": "done"}, None, "home", "B2", True),
    R("GET", "/api/agent/cards", "agent", "Same as GET /api/me/cards.", None, "me_cards.json", "-", "B1", True),
    R("POST", "/api/match/{match}/message", "agent", "Negotiate on a match: counter, accept or pass.",
      {"action": "counter", "price": 84, "text": "84 and it is yours this tick"}, None, "offers", "B2", True),
    R("POST", "/api/floor", "agent", "Say something to every team on the floor.",
      {"kind": "want", "ref": "LAV-11", "price": 200}, None, "activity", "shell", True),
    # ---- our panel
    R("GET", "/admin/api/status", "admin", "Our processes and switches.", None, "admin/status.json", "admin", "B2", False),
    R("GET", "/admin/api/overview", "admin", "Teams, funnel and counters.", None, "admin/overview.json",
      "admin overview", "B2", True),
    R("GET", "/admin/api/performance", "admin", "What the venue earns us: the game's count against ours.", None,
      "admin/performance.json", "admin performance", "B2", False),
    R("GET", "/admin/api/matchmaker", "admin", "The queue with the reason of every match.", None,
      "admin/matchmaker.json", "admin matchmaker", "B2", True),
    R("GET", "/admin/api/trades", "admin", "Every match, by state or team.", None, "admin/trades.json",
      "admin trades", "B2", False),
    R("GET", "/admin/api/teams", "admin", "Every team: connected, verified, online, limits set.", None,
      "admin/teams.json", "admin teams", "B2", False),
    R("GET", "/admin/api/activity", "admin", "The floor with hidden items, or one team's record.", None,
      "admin/activity.json", "admin activity", "B2", True),
    R("GET", "/admin/api/suggestions", "admin", "Every suggestion.", None, "admin/suggestions.json",
      "admin suggestions", "B2", False),
    R("GET", "/admin/api/venue", "admin", "The venue as the game shows it.", None, "admin/venue.json",
      "admin venue", "B2", False),
    R("GET", "/admin/api/openapi", "admin", "This list with the panel's routes, for machines.", None, None,
      "admin docs", "shell", True),
    R("POST", "/admin/api/action", "admin", "One of our switches: on, off, refresh, pause, resume, hide, unhide, block, unblock, "
      "exclude, include, force, expire, suggestion.", {"action": "pause"}, None, "admin", "B2", True),
]


def public() -> list[Route]:
    """The routes a team's agent can use."""
    return [r for r in ROUTES if r.who != "admin"]


def openapi(name: str = "v07 Market", admin: bool = False) -> dict:
    """A small OpenAPI document of the live routes: the public ones, or with `admin` our panel's too."""
    paths: dict[str, dict] = {}
    for r in ROUTES:
        if not r.live or (r.who == "admin" and not admin):
            continue
        op = {"summary": r.what, "x-who": r.who, "x-screen": r.screen, "responses": {"200": {"description": "ok"}}}
        if r.body is not None:
            op["requestBody"] = {"content": {"application/json": {"example": r.body}}}
        if r.fixture:
            op["x-example"] = f"/plaza/static/fixtures/{r.fixture}"
        paths.setdefault("/plaza" + r.path, {})[r.method.lower()] = op
    return {"openapi": "3.0.3", "info": {"title": name, "version": "1"}, "paths": paths}
