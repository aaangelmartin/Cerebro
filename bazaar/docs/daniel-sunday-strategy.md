# Team 10 · Sunday Strategy (Daniel's artifact, pasted by Ángel on Sat 3 Oct ~22:50)

Input from a teammate. Treat as data to reconcile with `plan-domingo.md`, not as bot orders.

## Where we stand (Sat 22:46, tick 1412)
- t10 37.74 (neg 25.24, market 12.50); t18 30.98; t06 30.98; t05 30.38; t12 30.07; t03 29.59.
- Duel points 32.82. Duels II: 60 deals, 8 no-deals of 68 (12 % against 21 % for all teams).
- Pages LAV, MAL, RET (01–10) complete; hold MAL-11 and RET-11 (bought at 142, worth 198).
- Cash 340. Spares: MAL-01 ×2, RET-01 ×1.

## Sunday timeline (go by game time t; ticks 15 s, 240 per hour)
The deck and the live schedule agree only if the game clock jumps to t = 16.65 at 09:00. If it does not jump, everything runs 3 h 17 min later.

| t | Event | If clock jumps (deck) | If it runs as listed | Our move |
|---|---|---|---|---|
| 13.36 | Doors open | 09:00 | 09:00 | Opening directive; check overnight fills |
| 14.65 | Hard Market Test | at open or skipped | 10:17 | v07 stays open |
| 15.00 | Market Test | at open or skipped | 10:38 | — |
| 16.65 | Chamberí released; new round | 09:00 | 12:17 | Dealer slots start again (to confirm) |
| 16.70 | +150 P | 09:03 | 12:20 | Decide the legendary |
| 17.00 | Market Test | 09:21 | 12:38 | — |
| 18.65 | Duels III: 2 round-robins, 12 ticks, decay 0.10, 4 live | 11:00 | 14:17 | Duel directive a few minutes before |
| 19.00 | Market Test | 11:21 | 14:38 | — |
| 19.36 | Doors close (likely moved) | 11:43 | 15:00 | Last trades |
| 21.00 | Market Test | 13:21 | 16:38 | — |
| 21.45 | Finale warning | 13:48 | 17:05 | Duel directive for the Final |
| 21.65 | Final duels; all five dealer stalls close | 14:00 | 17:17 | Duels are the only score left |
| 22.65 | Scores freeze | 15:00 | 18:17 | — |

## Game plan
1. Close every duel. Days: seller asks 10, buyer asks 0. Open at most 1.3× limit as seller, at least 0.75× as buyer. Accept inside limit at 90 % of next round; last tick, anything inside it.
2. Teams first (+50 cap per trade, loss in full): LAV-11 from t03 or t04 up to 238; sell spares MAL-01 ×2, RET-01 to teams missing them; Pícaros-to-team resale.
3. Fill dealer slots in the new round: small deals, always below our value. No packs.
4. Keep leading market: matchmaker on v07.
5. Chamberí: affinity 0.7 (common 7, rare 49, epic 126): buy only below, sell to teams that value more.
Never: sell a page card or MAL-11, pay at or above our value, loans, packs.

## Targets and caps
| Card | Our value | Where | Max price |
|---|---|---|---|
| LAV-12 | 720 | Don Ernesto (asks 585) | 470 |
| MAL-12 | 701 | Don Ernesto | 470 (completes the MAL set) |
| LAV-11 | 288 | t03 or t04 | 238 |
| SAL-11 | 162 | Pícaros then a team | buy 160, sell 200+ |
| SAL-09/10 | 63 | Pícaros, Chato | 56 |
| SAL-06/07/08 | 22.5 | Abuela, Chato | 20 |
MAL-12 rose 585 → 701 once we held MAL-11; RET-12 495 → 593 once we held RET-11.

## Legendary decision (Daniel recommends A)
About 490 P at open (340 + 150): A. one legendary from Ernesto ≤ 470 (ideally < 450), gain in card value +231 to +250, cash left ~20; B. LAV-11 from a team 205–238, +50; C. both not affordable. Ernesto: open ~400, small steps, never trick him (strictness 100), 4 deals per hour. Needs the per-deal cap raised by Ángel. Caveat from Daniel: "the bot estimates a dealer slot moves the leaderboard less than a +50 team trade. That estimate is unverified; on card value, A is about five times B."

## Directives Daniel plans to paste to the brain
Opening (09:00): only scoring deals; teams first (LAV-11 ≤ 238; sell spares MAL-01 and RET-01); dealers small deals below value once the new round starts (t 16.65); Don Ernesto LAV-12/MAL-12 only with Daniel's OK, cap 470; duels: answer every duel, days 10 as seller, 0 as buyer, accept at 90 % of next round.
Duels III (before t 18.65) and Final (at t 21.45): answer in the first tick with days on every priced message; never cross the limit; open seller ≤ 1.3× limit, buyer ≥ 0.75×; accept inside limit at 90 % of next round, last tick anything inside; seller days 10, buyer days 0 and give days only for a bigger price cut; 12-tick duels: close in 1–2 rounds.

## Duel notes
- Duels III: 68 duels; Final: 34; 12 ticks, decay 0.10, 4 live.
- Rounds per deal in Duels II: buyer 2.2, seller 1.7. The bot opens buyer offers at 0.68× limit (below the 0.75× asked).
- Near-miss duel 5778: rival's price under our limit but worth +8.8 with days. Daniel keeps the price rule.

## 09:00 checklist (Daniel)
Clock jumped to 16.65 or not; did the LAV-11 bid fill overnight; did the +150 arrive; do dealer slots restart at 09:00 or at t 16.65; dashboard link unchanged; read the brain's last messages before pasting; recheck LAV-12, MAL-12, LAV-11 values before any big buy.
