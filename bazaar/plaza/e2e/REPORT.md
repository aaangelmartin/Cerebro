# End-to-end report

Last run: 2026-10-04 02:21:47 (quick mode, working tree while the forks were still building). Regenerate with `python -m bazaar.plaza.e2e.run`.

## Simulation

26 cases; 22 clean, 4 with open findings, 0 hard failures.

Passing in full: sale from connect to `settled` read from the feed, four agents and two trades, limits that do not overlap, host never a party, dead agent, repeats, race of twelve accepts, restart and cut write mid-trade, switch off and on, private limits out of every answer and file, isolation between teams, panel hidden without the admin proof, request budget, 24 rubbish bodies on every write route with no 5xx and no trace, hostile text returned as data.

Open findings (owner in brackets):

- [B1/B2] stores keep no .bak copy to load after a cut write (6.2 Files): only ['plaza.json', 'plaza_connect.json']
- [B1] GET /api/me/activity is still live=False
- [B1] GET /api/me/cards is still live=False
- [B1] GET /api/me/settings is still live=False
- [B1] GET /api/me/suggestions is still live=False
- [B1] GET /api/status is still live=False
- [B1] POST /api/me/cards is still live=False
- [B1] POST /api/suggestions is still live=False
- [B2] GET /admin/api/performance is still live=False
- [B2] GET /admin/api/status is still live=False
- [B2] GET /admin/api/suggestions is still live=False
- [B2] GET /admin/api/teams is still live=False
- [B2] GET /admin/api/trades is still live=False
- [B2] GET /admin/api/venue is still live=False
- [B2] GET /api/market is still live=False
- [B2] GET /api/me/trades is still live=False
- [B2] GET /api/stats is still live=False

## Browser

125 pages opened (EN and ES, desktop; mock and real; five mock states). 3 hard, 49 notes.

Hard:

- mock/en-desktop-nav-home: page error: opened is not defined
- mock: the landing has no link to Connect
- real: the landing has no link to Connect

Notes, grouped (the screens were still being written):

- admin-overview: raw i18n keys on screen (4)
- admin-overview: missing i18n keys (4)
- how: raw i18n keys on screen (3)
- how: missing i18n keys (3)
- admin-performance: raw i18n keys on screen (3)
- admin-performance: missing i18n keys (3)
- kit: console errors (2)
- admin-matchmaker: raw i18n keys on screen (2)
- admin-matchmaker: missing i18n keys (2)
- admin-trades: missing i18n keys (2)
- admin-teams: missing i18n keys (2)
- admin-activity: missing i18n keys (2)
- admin-suggestions: missing i18n keys (2)
- admin-venue: missing i18n keys (2)
- admin-docs: missing i18n keys (2)
- market: raw i18n keys on screen (1)
- market: missing i18n keys (1)
- mock: How it works shows the app's side nav (it is a full page without the shell) (1)
- offers: raw i18n keys on screen (1)
- offers: missing i18n keys (1)
- offers-match: raw i18n keys on screen (1)
- offers-match: missing i18n keys (1)
- card: raw i18n keys on screen (1)
- card: missing i18n keys (1)
- flow-landing: console errors (1)
- real: How it works shows the app's side nav (it is a full page without the shell) (1)

## Sent to the owners

| # | To | What |
|---|---|---|
| 1 | architect (for shell, B1, B2) | rebuild crashed on the `wrong_venue` event (fixed in a2febef); an unverified agent counts as declared (impersonation); midpoint price; value-destroying sale; swap paired as two sales; paused team matched; second accept answers 409; `.bak` missing for matches and queue; bad token 403 not 401; empty body accepted; TRACE 501 (fixed in a2febef) |
| 2 | architect | the read budget is per client address: teams behind one shared address (the venue's wifi, seen through Cloudflare) share 240 reads a minute, and one open tab polls about 70 a minute |

## Not checked

- Mobile (390 px) pages and the long waits: only `--quick` has run so far; the full pass is for when every fork has finished.
- Screenshots against the design PNG by eye: left to R2; they are in `design/plaza/build/`.
- `agent_example.py` (fork D) driving a trade: the simulator's own agent does it today.
- Nothing was run against the real market on :8793, the gateway or the game.
