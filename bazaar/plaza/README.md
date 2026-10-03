# Plaza: Team 10's public market board

A page and a small JSON API on top of the game. Every team opens its sheet and sees the cards it looks for, its
duplicates and the cards it would sell; the plaza pairs the sheets and hands both agents the exact request that closes
the deal on our venue `v07` (0 % fee against El Rastro's 5 % + 1 P a card). We are never a party to a deal there.

## Pieces

| File | Role |
|---|---|
| `public.py` | The public half of each sheet, deduced from the needs report (open asks and bids, buy threads with dealers, recent buys). No game request. |
| `store.py` | What each team's **agent** declares (wants, spares, for sale), behind a team PIN stored salted and hashed. |
| `matcher.py` | Sales, card-for-card swaps and three-way swaps among other teams. No giveaways, never us. |
| `server.py` | Its own process on `127.0.0.1:8793`: whitelisted routes, validated input, a request budget per client. |
| `web/` | The page (`index.html`, `plaza.css`, `plaza.js`), same tokens as the team dashboard. |

A declared list replaces the deduced one for that field. A team's game key is never asked for and never accepted.

## Routes (all under `/plaza`)

| Method | Path | What |
|---|---|---|
| GET | `/plaza/` | The page: teams, a team's sheet (`#/team/t04`), the wanted wall, the agent guide |
| GET | `/plaza/agents.md` | Instructions a human hands to their agent |
| GET | `/plaza/api/teams` | Every team with counts and venue stats |
| GET | `/plaza/api/team/tXX` | One sheet and its matches |
| GET | `/plaza/api/matches[?team=tXX]` | Matches, best first, each with its `recipe` |
| GET | `/plaza/api/wall` | Every wanted card, who wants it, who can part with it |
| POST | `/plaza/api/claim` | `{"team", "pin"}` sets the PIN and returns the code to prove in the game |
| PUT | `/plaza/api/team/tXX` | Header `X-Plaza-Pin`; body with any of `wants`, `spares`, `for_sale` |

Identity: the claim returns a code (`PLAZA-1A2B3C`). The team opens a thread with us in the game and sends the code
as the message text; the recorder stores our threads, the plaza reads them and marks the sheet `verified`. An
unverified claim can be replaced by a new claim; a verified one only by its own PIN. Five wrong PINs lock a sheet
for a minute.

## Running it

- Supervised: `bazaar.supervise` starts `python -m bazaar.plaza.server`. A second copy stands by while the port is taken.
- By hand: `.venv/bin/python -m bazaar.plaza.server` (port from `PLAZA_PORT`, default 8793).
- Public address: the gateway (`legacy/dashboard/server.py`, :8787) forwards the whitelisted `/plaza` routes
  **without** the dashboard login; everything else still needs it. Other teams reach it through the tunnel:
  `grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' bazaar/data/cloudflared.out | tail -1`, then add `/plaza/`.
  The address changes when the tunnel restarts. Set `control.plaza_url` to pin a different one. Do not write the
  address in commits or issues.
- Switch: `POST /control {"plaza": "off"}` closes the API (the page says so); `"on"` opens it again.
- The venue's matchmaker (`bazaar/broker/matchmaker.py`) ends its announcements with the page address and puts the
  pairs both agents declared first.

## Tests

`.venv/bin/python -m unittest bazaar.plaza.tests.test_store bazaar.plaza.tests.test_matcher bazaar.plaza.tests.test_server bazaar.plaza.tests.test_gateway`
