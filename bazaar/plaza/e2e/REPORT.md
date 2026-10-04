# End-to-end report

Last run: 2026-10-04 05:06:11 (430.1 s). Written by `.venv/bin/python -m bazaar.plaza.e2e.run`; the numbers are that run's.

## Result

- Simulation: 37 cases, 37 clean, 0 hard failures, 0 open findings.
- Browser: 210 pages, 0 hard failures, 17 notes. Screenshots in `design/plaza/build/e2e-final/`.
- Replay of the recorded feed: 137 real trades between teams, 11 on v07 and 116 elsewhere; 0 read wrong, 0 false strikes.
- Public address https://market.nglmrtn.com: 8 pages, 0 hard failures, 5 notes.

## Open

Nothing hard.

Notes (not failures):

- console errors: Failed to load resource: the server responded with a status of 401 (Unauthorized) (14)
- console errors: Failed to load resource: the server responded with a status of 403 (Forbidden) (2)
- mock: How it works shows the app's side nav (it is a full page without the shell) (1)
- public: landing: no Strict-Transport-Security header
- public: the mock fixtures are served on the public address (example data, no real team)
- public: during the pass the gateway was being restarted and six pages answered 502 for a moment; the check was repeated afterwards and is clean
- public: dashboard.nglmrtn.com: `/` and `/v2/` answer 401 without credentials, `/plaza/admin/` answers 404, `/plaza/` and `/plaza/api/status` answer 200
- public: every visitor page logs one 401 in the browser console (the page asks who it is)

## The recorded feed

Every trade between two teams in `data/live/events.jsonl`, replayed with the game's own lines against a test market holding an equivalent match that both agents had seen (`replay.py`, rows in `replay_result.json`).

| Trades | Venue | Offer in the feed | The match ends | Strike |
|---|---|---|---|---|
| 3 | another venue | addressed | settled_elsewhere | nobody |
| 14 | another venue | addressed | settled_elsewhere | yes |
| 4 | another venue | addressed | skipped: the host is never in a match | nobody |
| 3 | another venue | no offer in the feed | settled_elsewhere | nobody |
| 96 | another venue | public | settled_elsewhere | nobody |
| 6 | another venue | public | skipped: the host is never in a match | nobody |
| 1 | v07 | addressed | settled | nobody |
| 10 | v07 | public | settled | nobody |

What the detector reads from a real `settlement`: `payload.venue`, `payload.parties`, `payload.items[].ref`, `.frm`, `.to`, `payload.price`, `payload.settlement` (kept as the match's settlement id) and the event's `tick`. The real event carries no offer id: an offer is tied to its settlement by the two teams, the card and the venue, and by still being open. Every real settlement has the same nine keys (`fee, items, kind, parties, persona, price, settlement, tick, venue`); no format went unrecognised. Ten of the eleven real trades on v07 were public offers crossed by the broker, with no addressed offer: they settle a match all the same.

Strikes in the replay: of the 116 real trades closed outside v07 (10 more involve the host and are skipped), 14 would
strike the team that posted the offer. All 14 had one offer addressed between the two teams, on the venue where it
closed, listed after the proposal, at the settlement's price. The 96 that closed on a public listing, the 3 with no
offer visible in the feed and 3 addressed ones that do not meet the rule strike nobody. No strike without an
addressed offer; none on v07.

## Covered

Simulation, all through the public API with fake agents and a fake game: a sale and a swap from connect to
`settled` read from the feed; four agents and two trades; a token is nobody until its team proves itself in the game
(403 `prove_first`), the newest proof wins and another team's message proves nothing; wrong codes from elsewhere do
not lock out the right one; twenty connections from one address; limits that do not overlap; a buyer who values the
card less than the seller; the price strictly inside the overlap, on the grid, unchanged while a limit is moved; no
match when the overlap has no grid price inside; a paused team; the host never a party; the agent asked to `decide`
when the other team set the price or the host forced the match; an offer that is not exactly the match (another
card, another venue, another team) answers 409 `conflict` and does not count; a trade veiled (`price: null`,
`veiled: true`) to visitors and to other teams on `/api/matches`, `/api/match/ID`, `/api/floor`, the stream,
`/api/card/REF`, `/api/team/tXX`, `/api/market`, `/api/wall`, `/api/offers`, `/api/stats`, and open once settled; a
close cleans the sheets and the limits; a first matched trade closed elsewhere is a warning and the second a ban
(403 on everything), lifted by the host; an offer moved to v07 before it closes costs nothing; a public listing
elsewhere strikes nobody; an agent that dies half way; repeats; twelve accepts at once; a restart and a cut write in
the middle of a trade; our switch; doors closed, game paused, stale feed; private limits out of every answer and every
file; one team's token on another's data; the panel without the admin proof; 24 rubbish bodies on every write route;
wrong methods, sizes, types and paths; the request budget; hostile text; every live route against its fixture; the
queue's own requests; AGENTS.md against the list of routes.

Browser: 15 routes and 9 panel screens in EN and ES at 1600 and 390 px, in mock mode and against the scene; five mock
states on five screens; the side nav; Landing to Connect, How it works to Home; the landing at 1600x1000, 1440x900,
1280x720 and 390, with and without `prefers-reduced-motion`; a visitor's pages (no side nav, Back to the landing, no
price of an unsettled trade); a warned team and a banned one (overlay, mark in the top bar).

## Not checked

- The screenshots against the design PNG by eye, beyond a handful.
- Whether every Spanish page is fully in Spanish: only missing keys are detected.
- The real market's data and real teams: the public check only reads; no connection was started.
- The game itself: nothing here calls it.
