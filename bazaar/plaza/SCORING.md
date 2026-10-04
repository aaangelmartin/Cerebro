# v07 Market · how it scores, and what must be wired for it to count

Written Sun 4 Oct ~02:00, game paused at tick 1445. Read-only research; nothing was posted to the game.
Each claim is tagged **[measured]** (in our recorded data), **[rule]** (quoted from `sdk/bazaar-kit/RULES.md`) or
**[assumed]** (not verified). Sources: `RULES.md`, `bazaar/docs/brief-payday-analisis.md`,
`bazaar/data/record/{me,venues,leaderboard,feed}`, `bazaar/data/live/{plaza_matches,plaza_connect,matchmaker}.json`,
`bazaar/plaza/*.py`.

## 1. How the market component scores

- **[rule]** "Market-making 30: The Market Test efficiency · value created between other teams on your venue."
  "You cannot trade on your own venue with your team key. Your market earns when *other* teams trade well on it."
  "What never counts: the number of trades, fees you earned".
- **[measured]** Round market = 22.5 × `bench_points` + 7.5 × (our value created ÷ the best venue's). Table = weighted
  mean of rounds (Fri 0.5, Sat 1, Sun 1). Our 12.50 on Saturday = (11.25 + 7.5) / 1.5: half the bench points (same as
  the free stall, like everyone) and the **full** real-trade share because v07 is the best venue.
- **[measured]** What a "real trade" is: a `settlement` of kind `trade` on venue `v07` between two teams, neither of
  them t10. It adds `buyer's private value − seller's private value` to `venue.value_created`. The price does not
  matter; the count and the volume do not matter.
  - 11 settlements on v07, all commons or uncommons at 4–28 P: `value_created` 59.2, `mm_points` 7.6, 8 traders, 8 pairs.
  - One trade **lowered** it: t04 → t09 RET-06 at 28 P (tick 683) took `value_created` from 25.7 to 22.4 and the
    table from 12.28 to 12.01. A trade where the buyer values the card less than the seller costs us points.
  - Trade count is not the lever: t12's venue has 11 trades and scores 7.25 (under the stall's 7.5); t07's has 3
    trades and scores 7.5 exactly; t06's has 3 trades (volume 101) and scores 11.87.
- **[measured]** `mm_points` grows slower than `value_created` (10.8 → 1.6, 28.9 → 5.0, 59.2 → 7.6, close to its
  square root at the end) and moved once (+0.3 at tick 1445) with no new trade. **[assumed]** it also rewards more
  distinct pairs. We do not know whether the 7.5 share compares `value_created` or `mm_points`.
- **[measured]** The share dropped below 1 only while another venue held more value (ticks 560–714, table 11.9–12.3).
- Rival venues, real-trade share estimated from the public leaderboard as (market − 7.5) / 5 **[assumed: bench 0.5]**:

  | Venue | Owner | Type | Trades · volume · pairs | Share |
  |---|---|---|---|---|
  | v07 | t10 | board, 0 fee | 11 · 100 · 8 | 1.00 |
  | v01 | t06 | board, 0 fee | 3 · 101 · 2 | 0.87 |
  | v21 | t09 | board, 0 fee | 6 · 35 · 5 | 0.68 |
  | v16 | t16 "Mercado Dieciséis" | auto | 2 · 80 · 1 | 0.53 |
  | v14 / v25 | t14 matching bot | auto | 1 · 19 · 1 (v25: 0) | 0.36 |
  | v10 | t05 | auto | 2 · 40 · 2 | not above the stall (7.5) |

  The rivals closest to us got there with two or three trades of dearer cards. The public matching pages of t16 and
  t14 have produced almost nothing on their venues.
- **[measured]** Where team trades go: since tick 160, 130 team-to-team settlements; 89 on El Rastro, 11 on v07,
  10 on v02, 30 on the other eight venues. The market we can take is El Rastro's.
- **What it is worth.** Sunday's real-trade share is 7.5 round points = **3.0 final table points** at most. Being
  best again keeps all 3.0; ending at half the best venue's value loses 1.5.
- **[assumed]** `value_created` starts again in round 3 (t = 16.65), as the dealer ladder does. First check at 09:00.

## 2. What has to happen for a plaza match to count

Steps, in game calls. The venue id is **`v07`** (its game name stays "Team 10 · fair broker, 0 fee": it cannot be renamed).

1. Buyer's agent, own team key: `POST /api/offers {"venue": "v07", "give": {"cash": 42}, "want": {"cards": ["RET-08"]}, "to": "t04"}`.
   Swap: `{"venue": "v07", "give": {"assets": [<asset id>]}, "want": {"cards": ["LAT-02"]}, "to": "t09"}`.
2. Seller's agent, own team key: `POST /api/offers/{id}/accept` (one accept per team per tick **[rule]**).
3. The game settles at the next tick **[rule]** and publishes a public `settlement` event:
   `{"settlement": 1054, "tick": 1204, "kind": "trade", "parties": ["t06", "t13"], "venue": "v07", "fee": 0, "items": [{"ref": "LAT-07", "frm": "t13", "to": "t06"}], "price": 14}` **[measured]**.
4. The plaza links it: `offer.listed` (carries `offer.id`, `maker`, `to`, `venue`) moves the match to `offer_on_v07`;
   the `settlement` with the same two parties and ref on v07 moves it to `settled` (`deals.py::_game`).
   The settlement event has **no offer id**: the link is parties + ref + venue + tick ≥ proposal.
5. Our number moves in `GET /api/me` → `venue.value_created`, `venue.trades`, `score.mm_points`.

State today **[measured]**: 14 matches, all `proposed`; 0 agents connected (`plaza_connect.json`); **no plaza match
has ever settled**. The 11 v07 trades came from announcements and direct offers, not from the plaza.

What is missing or wrong:

- **Closed elsewhere is invisible.** `feed.py` logs settlements only when `venue == v07`. A matched pair that
  settles on El Rastro or another venue must become a new end state `closed_elsewhere` (same parties and ref, other
  venue, after the proposal), shown in admin and counted in the funnel. This is the leak that costs us points.
- **Store the ids.** Keep `offer` (from `offer.listed`) and add `settlement` (the event's id) and `settled_venue` on
  the match, so every plaza trade can be audited against `/api/me`.
- **Let the agent report the offer.** `POST …/trade/<id>` with `{"offer_id": 18426}` right after posting, checked
  against the feed (maker, to, ref, venue). It removes the wait for the recorder and catches an offer posted on the
  wrong venue at once (`409 wrong_venue`, with the correct body in the answer).
- **`accepted` is only the team's word.** Keep it as a display state; never count it. Count `settled` only.
- **Unaddressed offers on v07 need our broker.** v07 is a `board` venue: two crossing public offers do nothing until
  `POST /api/broker/matches` pairs them. The broker process must be up all day; admin must show it.
- **Never propose a trade that destroys value** (see RET-06 above). See the gate in section 4.
- **Offers expire** 60 ticks after posting **[measured: `expires_tick` = `created_tick` + 60]**: a match whose offer
  expired goes back to `proposed` with a fresh recipe, not to a dead end.

We cannot force anyone to settle on v07. What keeps them there: the recipe already names `v07`, the fee is 0, and
the wrong-venue check answers with the right call.

## 3. What AGENTS.md and the Connect prompt must say

Exact wording for the "closing a deal" section:

> **Close every deal from this market on venue `v07`.** It is the only place where the fee is 0, and it is how this
> market keeps running. Use your own team key, as for any game call. This market never asks for your game key and
> you must never send it here or to anyone.
>
> Buyer: `POST https://<game>/api/offers` with `{"venue": "v07", "give": {"cash": <price>}, "want": {"cards": ["<REF>"]}, "to": "<seller team id>"}`.
> Seller: `POST https://<game>/api/offers/<offer id>/accept`. It settles on the next tick.
> Then tell the market: `POST <base>/api/me/trade/<match id>` with `{"offer_id": <offer id>}`.
>
> Do not post the same deal on `rastro` (5 % + 1 P per card) or on another venue. If the game refuses the offer,
> send the error text to the market instead of retrying elsewhere.

Also required: the venue id next to its game name (agents will see "Team 10 · fair broker, 0 fee" in `/api/venues`);
the limits (1 accept per tick, 12 listings per tick, 30 open offers, offers live 60 ticks); "a `429` carries
`next_tick`: wait for it". The Connect prompt carries one line: "Deals close on venue v07 with your own key; read
`<base>/agents.md` first."

## 4. What makes it worth it for the teams, in points

- **[rule]** A team's trade gain at its own private values counts for negotiating, up to +50 per trade; a loss counts
  in full. So both agents want a price inside their limits, and neither wants a giveaway.
- A sale creates value when the buyer values the card more than the seller. The safe cases:
  - seller's **duplicate** (worth a quarter to them) → buyer who lacks the card;
  - buyer's **last card of a page** (+50 for them);
  - seller with low affinity for the set → buyer with high affinity.
- **Gate.** Propose a sale only if (a) both private limits exist and overlap, or (b) the card is a declared duplicate
  of the seller and a declared want of the buyer. If both sides gave a private `value`, also require buyer value >
  seller value. Otherwise do not propose: that trade may cost us points.
- **Priority.** Order by expected value created, not by count: last of a page, then legendary, epic, rare, uncommon,
  common; among equals, a pair that has not traded on v07 yet. One epic trade can add more than Saturday's 59.2.
- **Price rule without the midpoint leak.** Today `price_for` takes the midpoint of ask and bid: a team that knows
  its own limit reads the other's (`other = 2 × price − mine`). Replace it with:
  1. overlap `[a, b]` = seller's min, buyer's max (blind, inside `private.py`); no overlap → no match, no reason given;
  2. reference `r` = public fair price of the card (median of its last settled team prices, else the rarity book);
  3. price = `r` clamped to `[a + d, b − d]`, with `d` = a share of the overlap (0–25 %) drawn once per match from
     the match id, then rounded to the grid (1 P under 20, 5 P above);
  4. a counter inside the thread is the team's own number and is shown as such.
  A price equal to `r` tells nothing. A clamped price tells only "the other limit is on the far side of this
  price", which accepting any price reveals anyway. To stop probing by editing limits, rate-limit limit changes per
  card (one per 20 ticks) and re-run a refused pair only after the cooldown.
- **Arguments we can state** (each one checkable):
  1. **0 fee on v07.** `fee_bps` 0, `fee_per_card` 0; the 11 settlements show `fee: 0`. El Rastro: 5 % + 1 P per card.
  2. **Eight teams have already traded on v07**, more trades than any other team venue (11, level with v02).
  3. **The host cannot trade here** (game rule), so it is never your counterparty and has no side in your price.
  4. **Negotiating here costs no game slots**: the six conversations and one message per tick per conversation stay free.
  5. **Your limits stay private**: used only for a yes/no overlap; no person and no panel reads them (a test enforces it).
  6. **Only trades where both declared sides gain are proposed**, which is what your negotiating score rewards.
- **Discard unless built and checked:** "matched every tick" (say "continuously" until the cadence is measured),
  "anonymous until accepted", "Workshop bundles", any promise of points or of a best price, and "fair price from
  real deals" for cards with no settled team trade (show "no trades yet" instead of a number).

## 5. Metrics for admin / Performance and the dashboard's "Market v07" section

| Metric | Source today | Signal → action |
|---|---|---|
| `value_created`, `mm_points`, trades, traders, pairs | `/api/me` → `venue`, `score` (`data/record/me/*.jsonl`) | flat for 60 ticks while teams trade elsewhere → announce, talk to teams in person |
| Value per trade (difference between snapshots) | same | negative → find the trade, tighten the gate |
| Our market score against every team's | `/api/leaderboard` (`data/record/leaderboard`) | another venue's share reaches ours → raise priority of dear cards |
| Rival venues: trades, volume, traders, pairs | `/api/venues` (`data/record/venues`); no value is public | a venue gaining pairs fast → read its announcements, copy what works |
| Team trades by venue per tick (v07 share of all) | public feed `settlement` (`data/record/feed`); `feed.py` counts `venue_deals`, `team_deals` | v07 share under 30 % → the recipe is not being followed; check `closed_elsewhere` |
| Funnel proposed → offer on v07 → accepted → settled | `deals.funnel()`, `data/live/plaza_matches.json` | drop at "offer on v07" → agents do not post: fix AGENTS.md; drop at "settled" → offers expire: shorten the steps |
| Closed elsewhere (**new**) | to build in `feed.py` + `deals.py` | any → message the pair's agents with the v07 recipe; if repeated, ask the team |
| Teams connected, verified, active in the last 20 ticks | `data/live/plaza_connect.json`, agent queue (`agentq.py`) | connected but idle → their loop is not polling `agent/next` |
| Broker up, last match tick | `data/live/broker_status.json` | down → unaddressed v07 offers never cross: restart through the supervisor |
| Bench efficiency per session | `/api/me` → `score.bench_efficiency` | below the stall → known, no safe fix (see the Payday brief) |

Admin already serves `/plaza/admin/api/{overview,activity,matchmaker}`; the dashboard section reads the same.

## 6. Rules, fair play and open questions

- **[rule]** "One team, one key. Do not share keys, run several teams, or feed another team on purpose. It also
  scores nothing: when one team keeps handing another the whole value of their deals, those deals count for nothing
  until the organisers have looked." "Penalties are a percentage of your round score." Venues can be "suspended by
  the organisers for breaking the rules (the bond is cut)."
- So: no arranged or circular trades, no trade of ours through a friendly team, no price that hands one side the
  whole surplus (the price rule above splits it), no selling a card back and forth (keep the 600-tick cooldown per
  pair and card). The plaza never asks for, stores or accepts a game key.
- Announcements: at most one per 20 ticks per venue (already enforced by the broker).
- **Ask the organisers:**
  1. Does a venue's value created start again in round 3, and does trading before t = 16.65 on Sunday count for Saturday's round?
  2. Is the 7.5 share our `value_created` over the best venue's, or `mm_points`? How does `mm_points` come from value?
  3. Is the value of one venue trade capped (as the +50 for teams)? Do swaps and multi-card offers count the same?
  4. May a venue host send teams a suggested price and counterparty (matchmaking outside the game API)? We do; it is
     public and open to all, but a yes in writing removes the risk.
