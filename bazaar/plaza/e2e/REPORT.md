# End-to-end report

Last run: 2026-10-04 02:39:31, full pass (285.7 s), on the working tree while the building forks were finishing. Regenerate with `.venv/bin/python -m bazaar.plaza.e2e.run`; the numbers below are that run's.

## Simulation (`tests/test_e2e_sim.py`, strict)

26 cases: 25 clean, 1 with an open finding, 0 hard failures.

Clean: a sale from connect to `settled` read from the feed; a swap; four agents and two trades; limits that do not overlap; a buyer who values the card less than the seller; the price is not the midpoint of the limits; a paused team; the host never a party; an agent that dies half way; repeated acks and accepts; twelve accepts at once; a restart and a cut write in the middle of a trade; a deal closed on another venue ends `settled_elsewhere`; our switch; doors closed, game paused, stale feed; private limits out of every answer and every file under `live/`; one team's token on another's data; the panel without the admin proof; an unverified agent; 24 rubbish bodies on every write route (no 5xx, no trace); wrong methods, sizes, types and paths; the request budget; hostile text; every live route against its fixture; the queue's own requests; AGENTS.md against the list of routes.

Open:

- [B1/B2] stores keep no .bak copy to load after a cut write (6.2 Files): only ['plaza.json', 'plaza_connect.json']

## Browser (`browser.js`)

185 pages: 15 routes and 9 panel screens, EN and ES, 1600 and 390 px, in mock mode and against the scene; five mock states on five screens; the side nav; Landing to Connect, How it works to Home. 0 hard failures, 25 notes. Screenshots: `design/plaza/build/`.

No page error, no missing script or style, no 5xx, no hostile text turned into markup, every nav entry leads to a screen that draws, the panel answers 404 without the admin proof.

Notes:

- missing i18n keys: status.unknown (18 pages)
- console errors: Failed to load resource: the server responded with a status of 404 (Not Found) (4 pages)
- scrolls sideways by 6px (2 pages)
- console errors: Failed to load resource: the server responded with a status of 401 (Unauthorized) (1 pages)

Where: `status.unknown` on the panel's status box against the real API (a process whose state the rig cannot know); the 404 on `/plaza/_kit` in real mode; the 401 on the landing without a session (the page asks who it is); 6 px of sideways scroll on How it works at 390 px.

## Sent to the owners

1. To the architect, for shell, B1 and B2: the board froze on the `wrong_venue` event; an unverified agent counted as declared; midpoint price; value-destroying sale; swap paired as two sales; paused team matched; second accept answered 409; `.bak` missing; bad token 403; empty body accepted; unknown methods 501. All but `.bak` for `plaza_matches.json` and `plaza_agentq.json` no longer reproduce.
2. To the architect: the request budget is per client address. Teams behind one shared address (the venue's network, as Cloudflare reports it) share 240 reads a minute, and one open tab polls about 70 a minute.
3. To the architect: `status.unknown` has no text; How it works scrolls sideways at 390 px; `/plaza/_kit` asks for something that answers 404 outside mock mode.

## Not checked

- The screenshots against the design PNG, by eye: two were opened (Offers with a match, Home in Spanish at 390 px); the rest are for R2.
- `agent_example.py` (fork D) driving a trade through the rig: the rig's own agent does it today.
- Whether the Spanish pages are fully in Spanish: only missing keys are detected; text the server sends stays as sent.
- The real market on :8793, the gateway and the game: never touched, by design.
- The final pass after R1 and R2: run the one command again.
