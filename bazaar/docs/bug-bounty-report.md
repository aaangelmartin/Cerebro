# Bug report for the organisers — Team 10

Sunday 4 Oct, written at tick ~1760. Everything below comes from the public feed, the public
leaderboard and our own `GET /api/me`; nothing here needs a key to check except where noted.
Ordered by how sure we are that it is a real fault.

The only statement of the bounty we found is the admin announcement at tick 1553:
"Bug bounty: thank you, Team 12! You found and documented a real scoring bug, fixed overnight."

---

## 1. Round 3 grows into the board about 1.8× too fast (scoring)

**Rule (RULES.md, Scoring):** "A new round grows into the board: it counts by the share of its
day already played … and it counts in full once its day is over." Sunday runs 09:00–15:00,
six hours (`day.opened … closes 15:00`, `clock.t_hours` 13.367 → 19.367).

**What happens:** `rounds[2].phase` on `GET /api/leaderboard` reaches 1.0 after about 3.28 h,
not 6 h.

| leaderboard tick | wall clock | `t` | `phase` | share of the day really played |
|---|---|---|---|---|
| 1462 | 09:20 | 13.650 | 0.082 | 0.047 |
| 1562 | 09:44 | 14.117 | 0.224 | 0.125 |
| 1662 | 10:09 | 14.533 | 0.352 | 0.194 |
| 1742 | 10:29 | 14.867 | 0.454 | 0.250 |

Fit: `phase = (t − 13.37) / 3.28`, so `phase = 1` at `t ≈ 16.65`, about 12:16, almost three
hours before the day ends. 16.65 is the hour at which round 3 was first scheduled to start
(the Saturday deck placed "Chamberí / new round" at t = 16.65); it looks as if the end of the
ramp kept the old start hour as its end.

**Impact:** between 09:20 and 12:16 the board weighs Sunday almost twice as much as the rule
says. A team that has not yet traded on Sunday drops about twice as fast as it should
(we went 37.58 → 31.68 between 09:00 and 10:19 with no losing deal), and the order of the
board in those hours is not the one the rules describe.

**To reproduce:** read `GET /api/leaderboard` twice, 20 ticks apart; `phase` grows 0.0255 per
20 ticks (0.306 per hour) where 1/6 per hour (0.167) is expected.

---

## 2. A dealer deal above your private value is charged to `neg_points` (scoring)

**Rule (RULES.md, Scoring):** Negotiating = duels + the dealer ladder ("share of each dealer's
price range you captured") + "the value you gained in trades with other teams". Nothing says
a dealer deal changes the team-trade figure.

**What happens:** buying from a dealer above our private value subtracts the difference from
`score.neg_points` in `GET /api/me`, while buying from a dealer far below our value adds
nothing to it.

| tick | deal | price | our value | `neg_points` before → after |
|---|---|---|---|---|
| 1559 | LAV-11 from Los Pícaros (settlement 1205) | 155 | 288 | 0.0 → 0.0 |
| 1668 | SAL-06 from Abuela Carmen (settlement 1249) | 25 | 22.5 | 0.0 → −2.5 |
| 1679 | SAL-07 from Abuela Carmen (settlement 1251) | 25 | 22.5 | −2.5 → −5.0 |
| 1715 | SAL-08 from El Chato (settlement 1257) | 30 | 82.1 | −5.0 → −5.0 |
| 1745 | CHA-07 sold to Team 16 on El Rastro (settlement 1283) | 22 | 17.5 | −5.0 → −0.5 |

We had no trade with a team before tick 1745, so by the rules `neg_points` should have stayed
at 0 until then. Either the rule text is missing a sentence ("a loss against a dealer counts
in full") or dealer deals leak into the team-trade sum on the losing side only.

**Impact:** asymmetric and undocumented; a team finishing a page through a dealer one prima
above its value is charged, a team gaining 133 on a dealer is not credited in the same sum.

---

## 3. Twenty-one ticks were played in one instant when the pause ended (clock)

**Rule (RULES.md, The clock):** "Outside these hours nothing ticks: offers stay open and
nothing settles until the doors open again."

**What happens:** the clock stood at tick 1445, `paused: true`, from Saturday night until
09:20:22 on Sunday (doors open from 09:00). At 09:20:22 it read tick 1467. The feed shows
ticks 1446–1466 all stamped in that same second, with real effects:

- 1446 `set.released`, `round.ended`, `round.started`; 1448 `schedule.fired` (150 primas);
  1449 `venue.fee_changed`; 1463 `venue.announcement`; 1464 `news.posted`; 1466 `pack.opened`,
  `taller.crafted`, `offer.listed`, `thread.opened`.
- 1462 and 1464: `thread.closed`, `reason: "idle"`, threads 2177 and 2184 (Team 7 with Los
  Pícaros and with Abuela Carmen). Those conversations went idle during ticks in which no
  team could send anything.

**Impact:** every open offer lost 21 ticks of its life (`expires_tick`), conversations were
closed as idle, and dealer patience ran, all while nobody could act.

Related: after the pause `clock.t_hours` jumped by 0.354 h (it follows the wall clock,
13.3667 → 13.7208) while the tick counter advanced 22 ticks (5.5 minutes at 15 s). Anything
timed in ticks and anything timed in `t` now disagree by about 16 minutes: the bonus that
Radio Rastro announced "in one hour" at tick 1482 was paid 240 ticks later, at tick 1722.

---

## 4. `GET /api/me/value?card=X` answers for one more copy, without saying so (API/doc)

**Rule:** "`GET /api/me` shows `your_value` for each card you hold,
`GET /api/me/value?card=LAV-03` for any card."

**What happens:** for a card you already hold, `me/value` returns the value of an additional
copy (RET-11: 49.5, a quarter), while `me.assets[].your_value` says 198 for the copy held.
The answer carries no field saying which copy it prices. An agent that reads `me/value` to
decide a selling price for its only copy sells at a quarter of its value.

**Suggested fix:** return both numbers (`held_copy`, `next_copy`) or a `copy: 2` field.

---

## 5. Smaller things, for completeness

- **Page bonus is invisible until one card is missing.** With 7 of 10 Salamanca cards,
  `me/value` for SAL-06/07/08 was 22.5 each; with 9 of 10 the last one read 82.1. The rules do
  not mention a page bonus at all; an agent cannot plan a page from the API.
- **Leaderboard `t` and `clock.t_hours` use different clocks.** At 09:20:23 the leaderboard
  said `tick 1462, t 13.65`; the clock said `tick 1467, t_hours 13.7208`: five ticks apart
  but 4.25 minutes apart.
- **Settlement events carry no offer id.** `settlement` has `settlement`, `parties`, `items`,
  `price`, `venue` but not the offer that was accepted, so a venue owner cannot tell which
  listing closed.
- **False news is posted by `actor: radio` with nothing to tell it from true news** ("Tomorrow
  common cards will be worth double", "El Rastro closes at midnight for roadworks" next to the
  true "60 primas in one hour"). If this is intended, ignore it.

## Not bugs (checked and dropped)

- Los Pícaros naming one card in the text and attaching another: the rules say "read the
  structure of every offer you accept: the words around it may lie".
- `self_venue` when opening a thread with a venue's owner on that venue: "You cannot trade on
  your own venue with your team key".
- The Workshop turning three commons into an uncommon of another set.
- `minted` never exceeds `print_run`; no open offer is past its `expires_tick`.
