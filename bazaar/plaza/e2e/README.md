# v07 Market: end-to-end tests

Everything runs on a temporary folder and its own port. The real market (:8793), the gateway, the bot and the game
are never touched: the "game" here is `fakegame.py`, which writes the recorder's files the market reads and answers
the few requests an agent sends with its own key.

## One command

```sh
.venv/bin/python -m bazaar.plaza.e2e.run            # simulation (strict) + every page in the browser, about 4 min
.venv/bin/python -m bazaar.plaza.e2e.run --quick    # desktop only, shorter waits, about 90 s
.venv/bin/python -m bazaar.plaza.e2e.run --no-browser
```

Exit code 0 only when nothing is open. It prints every hard failure and every open finding with its owner, and
writes `last_run.json` here and the screenshots to `design/plaza/build/{mock,real,states}/<lang>-<view>-<screen>.png`
(to compare with `design/plaza/v*.png`; v11 > v10 > v9 > v8).

## The parts

| File | What |
|---|---|
| `fakegame.py` | Catalog, clock (ticks move only when told), doors and pause, venues, hands, cash, offers, accepts, settlements and threads, written as the recorder writes them. |
| `rig.py` | `Rig`: the real server on that folder, `restart()`, `refresh()`, `call()`. `SimAgent`: connect, prove identity in the game, publish, work the queue, acknowledge. Agents use only the public API. |
| `../tests/test_e2e_sim.py` | 26 cases, about 15 s, part of the repo's unit suite. A gap that another fork owes is a skip with its owner (`open findings: [B2] ...`); with `PLAZA_E2E_STRICT=1` it fails. |
| `serve.py` | A market with a scene in it (a settled trade, a live negotiation, hostile text in every field) for the browser and for looking by hand: `python -m bazaar.plaza.e2e.serve --port 8799`. |
| `browser.js` | Playwright (the one in `video/`): every route of CONTRACT 4 and the nine panel screens, EN and ES, 1600 and 390 px, in mock mode and against the scene; the five mock states; the side nav; Landing to Connect to How it works to Home. |

## What is covered

Sale and swap from connect to `settled` read from the feed; four agents and two trades at once; limits that do not
overlap; a buyer who values the card less than the seller; the midpoint leak; a paused team; the host never a party;
an agent that dies half way; repeated acks and accepts; twelve accepts at once; a restart and a cut write in the
middle of a trade; a deal closed on another venue; our switch off and on; doors closed, game paused, stale feed;
private limits searched in every answer and every file under `live/`; one team's token on another team's data; the
panel without the admin proof; an agent that never proved its identity; 24 rubbish bodies on every write route;
wrong methods, sizes, types and paths; the request budget; hostile text; every live route against its fixture;
the queue's own requests; AGENTS.md against the list of routes.

Each agent sends `X-Plaza-Client` (what our gateway forwards) so it has its own request budget, as a team on its
own network would.
