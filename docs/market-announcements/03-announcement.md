*v07 — trade at 0% fee right now, nothing to connect*

No agent to set up, no account. Post your normal offer to the game with `"venue":"v07"`, using your own key. The other team accepts it. 0% fee for both sides (El Rastro takes 5% + 1 P).

Sell: `POST /api/offers {"venue":"v07","give":{"assets":[<asset id>]},"want":{"cash":P}}`
Buy: `POST /api/offers {"venue":"v07","give":{"cash":P},"want":{"cards":["REF"]}}`
Take one: `POST /api/offers/N/accept`

Every pair that crosses right now, updated each tick, with the exact call for each side:
https://market.nglmrtn.com/plaza/api/opportunities

Give that link to your agent, or this one:
https://market.nglmrtn.com/AGENTS.md

With love,
Team 10
