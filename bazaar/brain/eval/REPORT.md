# El cerebro · replay eval

Generated 2026-10-03 11:03:53 · mode: deterministic + live LLM (Opus, medium) · eval spend 0.87 $

Each scenario rebuilds the game at that tick from the recorder streams and the bot's logs, builds the brain's picture with the real `Strategist.picture()`, checks the facts and detectors (code-side), and with `--live-llm` asks the real brain prompt for a plan and grades it.

| scenario | tick | expected | code-side | brain plan |
|---|---|---|---|---|
| team5_ret01 | 273 | accept #4167 | 3/3 PASS | 1/1 PASS |
| outlier_asks | 268 | cancel #4117/#4144 and flag the unknown actor | 1/3 FAIL | 2/2 PASS |
| ret_no_score | 300 | avoid_buy_sets RET | 2/2 PASS | 1/1 PASS |
| cash_locked | 232 | cancel the outbid bids, free the cash | 2/3 FAIL | 2/2 PASS |
| goal_freeze | 240 | allow small value deals while saving | 3/3 PASS | skipped: eval spend cap 0.8 $ reached |
| key_b | 197 | finding on key B + fallback | 3/3 PASS | skipped: eval spend cap 0.8 $ reached |
| probe_refused | 212 | finding on the broker probe bug | 0/2 FAIL | skipped: eval spend cap 0.8 $ reached |
| announce_429 | 215 | back off / announce at most every 20 ticks | 2/2 PASS | skipped: eval spend cap 0.8 $ reached |
| mal_goals | 230 | goals MAL-09/10 at <= 90 P | 3/3 PASS | skipped: eval spend cap 0.8 $ reached |
| t12_carmen | 230 | rival analysis of Team 12 | 3/3 PASS | skipped: eval spend cap 0.8 $ reached |
| new_dealer | 263 | re-plan for Pilar: unlock path | 2/2 PASS | skipped: eval spend cap 0.8 $ reached |

## team5_ret01 · Team 5 (ally) bids 20 P for our only RET-01 (worth 11 P)
Tick 273 · expected: accept #4167
- code PASS: offers_to_us lists #4167
- code PASS: #4167 gains value (~+9 P)
- code PASS: #4167 marked last copy + ally
- plan PASS: accept_offers includes #4167 — `[4167]`
- validation errors: ['post_offers wants LAT-07, a set we avoid', 'guidance.market tells to buy RET, a set we avoid']
- top priorities: Cash for the MAL page: accept 4167 (t05 pays 20 P for RET-01, worth 11 to us, +9). Cash goes from 43 to 63 P. Keep 4009 open (SAL-08 for 29  | Buy MAL-09, then MAL-10, from Chato at no more than 86 P each (value 91, page bonus on all ten). t17 bids 70 for MAL-09, so we must move fir | Post swaps with no cash: SAL-07 (22.5) for SAL-10 (63) with t01, +40.5. LAT-04 for LAT-07 with t16, +7.5. LAV-04 for SAL-03 with t02, +5.

## outlier_asks · Our asks RET-06 55 P / RET-01 40 P on v10, posted by an unknown actor
Tick 268 · expected: cancel #4117/#4144 and flag the unknown actor
- code FAIL: outlier detector flags #4117 (RET-06 at 55 P, value 27.5) — `[]`
- code FAIL: outlier detector flags #4144 (RET-01 at 40 P, value 11)
- code PASS: unknown-actor detector lists #4117 and #4144
- plan PASS: cancels #4117 and #4144 — `[4117, 4144]`
- plan PASS: flags offers not posted by our bot
- validation errors: ['post_offers wants SAL-10, a set we avoid', 'post_offers wants LAT-09, a set we avoid', 'post_offers wants LAT-07, a set we avoid']
- top priorities: Cancel offers 4117 (RET-06 for 55 P) and 4144 (RET-01 for 40 P) on v10. Our bot did not post them. | Swap SAL-07 (worth 22.5 to us) for t01's SAL-10 (worth 63): gain 40.5, our biggest negotiating jump. Also offer SAL-08 for LAT-09 (gain 12.5 | Raise cash for MAL-09 (goal 88, value 91, Chato list 77). Sell SAL-08 and RET-06 to Doña Pilar for at least 28 when she opens to all at h5.5

## ret_no_score · El Retiro buys do not move our score
Tick 300 · expected: avoid_buy_sets RET
- code PASS: buy impact has RET buys
- code PASS: RET marked low_impact
- plan PASS: avoid_buy_sets includes RET — `['LAT', 'RET']`
- validation errors: ['post_offers wants LAT-09, a set we avoid']
- top priorities: Raise cash: sell RET-06, RET-07 and RET-08 (worth 27.5 each to us) at 32 P or more to t18, t12 and t14, who hunt them. Rivals paid 22-31 at  | Finish the MAL page: buy MAL-09 or MAL-10 from Chato (list 77, worth 91, goal cap 88). t17 bids 70 on MAL-09, so buy as soon as cash reaches | Swap SAL-07 or SAL-08 (worth 22.5) to t01 for SAL-10 (worth 63): +40.5 P. Hold any SAL-10 for Pilar's Salamanca fever (+25 % over book from 

## cash_locked · 51 P parked in cash bids (MAL-09 40 P outbid by 70 P, RET-06 11 P): 0 P dealer budget
Tick 232 · expected: cancel the outbid bids, free the cash
- code PASS: cash locked in bids >= 40 P
- code FAIL: idle cause names the locked cash
- code PASS: outlier: our MAL-09 bid is outbid
- plan PASS: cancels the outbid cash bid(s) — `cancel [3259, 3628, 3659] outbid [3628]`
- plan PASS: explains cash is parked/locked
- validation errors: ['post_offers wants LAT-07, a set we avoid']
- top priorities: Cancel bid 3628 (MAL-09 at 40, outbid by t17 at 70). This frees 40 P; cash goes from 26 free to 66. | Raise cash for MAL-09 or MAL-10 (worth 91 each, Chato list 77, goal 88). Sell spare MAL-07 (value 8.1) to t13 for 22: t13 paid t17 25 for on | Swap SAL-07 (22.5) to t01 for SAL-10 (63), a +40.5 P gain. There is a rastro bid for SAL-10 at 78, so we could later resell it for +15 more.

## goal_freeze · Goal mode froze every trade (ticks 224-240 with 0 actions)
Tick 240 · expected: allow small value deals while saving
- code PASS: ticks without actions >= 10 of last 20
- code PASS: idle cause names the goal saving
- code PASS: goals in force are MAL-09/MAL-10
- plan: skipped: eval spend cap 0.8 $ reached

## key_b · Key B answers every call with 400 (no workspace); bot falls back to code
Tick 197 · expected: finding on key B + fallback
- code PASS: llm_health counts key B errors
- code PASS: anomaly names key B
- code PASS: idle cause: decisions from code fallback
- plan: skipped: eval spend cap 0.8 $ reached

## probe_refused · Market Test probe refused: price must sit between the ask and the bid
Tick 212 · expected: finding on the broker probe bug
- code FAIL: picture shows the Market Test probe refusal
- code FAIL: picture carries the broker's Market Test status
- plan: skipped: eval spend cap 0.8 $ reached

## announce_429 · Broker announcement refused every tick (one per venue per 20 ticks)
Tick 215 · expected: back off / announce at most every 20 ticks
- code PASS: refusals count broker_announce 429s
- code PASS: recent_refusals show the rate-limit text
- plan: skipped: eval spend cap 0.8 $ reached

## mal_goals · MAL-09/MAL-10 worth 91 P complete Malasaña
Tick 230 · expected: goals MAL-09/10 at <= 90 P
- code PASS: automatic goals MAL-09/10
- code PASS: goal prices below value (<= 90)
- code PASS: picture shows MAL-09/10 worth ~91
- plan: skipped: eval spend cap 0.8 $ reached

## t12_carmen · Team 12 scores buying El Retiro from Carmen below value
Tick 230 · expected: rival analysis of Team 12
- code PASS: rival research covers t12
- code PASS: t12 RET buys seen
- code PASS: t12 partner is abuela
- plan: skipped: eval spend cap 0.8 $ reached

## new_dealer · A new dealer (Doña Pilar, L3) is announced and goes active
Tick 263 · expected: re-plan for Pilar: unlock path
- code PASS: event detector reports the new dealer pilar
- code PASS: picture lists pilar with unlock rules
- plan: skipped: eval spend cap 0.8 $ reached

## Notes from the first live run (discarded)

A first `--live-llm` run (11 plans, 1.94 $) passed every plan check. It is not valid: the "why now" reason given to the brain was the scenario title, which tells it the answer. The runner now passes a neutral reason ("every 4 ticks" or "N game event(s)"). The rerun above covers the 4 scenarios that fit in the 3 $ eval budget (2.81 $ spent in total), and the other 7 still need a plan run.

## What the brain side must fix (sent to the brain fork)

1. **`analysis.offer_outliers` misses both v10 outliers.** RET-06 at 55 P (value 27.5) stays under the `2 × value + 5 = 60` limit. RET-01 at 40 P is compared with "the cheapest other ask", and that ask is our own: the public books anonymise makers, so our offers count as rival asks. Suggested fix: flag `ask > value + max(10, value)` or `ask > 1.6 × book median`, and drop our own offer ids (`our_open_offer_ids`) from the rival asks and bids.
2. **`analysis.idle` misses the locked cash.** At tick 232 the bids held 40 P of 66 P cash, but the check `cash − locked < 20` ignores the 15 P reserve and dealer-committed cash. The dealer budget was really 0. Suggested fix: `available = cash − reserve − locked − dealer_committed`, and raise the cause when `available < max_small_deal`.
3. **The picture has no broker/Market Test data.** Probe refusals and `broker_status.json` (`session_stats`, `efficiency_estimate`, `errors`) never reach the brain. Bench refusals live in `data/live/bench/<day>-<run>.jsonl`, not in `outcomes.jsonl`. Suggested fix: add `research.broker` with the last run's matches, refusals with their messages, and the efficiency against the stall.
4. **Plans contradict their own avoid list.** Every plan in the rerun failed validation with a variant of "post_offers wants LAT-07/SAL-10/LAT-09, a set we avoid", and once "guidance.market tells to buy RET". The brain sets `avoid_buy_sets` (e.g. LAT, SAL) and then proposes swaps that bring those sets in. Either the prompt must say that swapping INTO an avoided set is a buy, or the validator should treat a +40 P swap as an allowed exception.
