# El cerebro · replay eval

Updated 2026-10-03 · code-side: deterministic run of all 11 scenarios (no API calls) · brain plan: real brain prompt (Opus 5.5, medium, purpose brain_eval). Eval spend: 2.81 $ earlier + about 1.48 $ in this run (cap 1.60 $ approved by the user).

Each scenario rebuilds the game at that tick from the recorder streams and the bot's logs, builds the brain's picture with the real `Strategist.picture()`, checks the facts and detectors (code-side), and with `--live-llm` asks the real brain prompt for a plan and grades it. The brain is given a neutral reason ("every 4 ticks" / "N game event(s)"), never the scenario title.

| scenario | tick | expected | code-side (now) | brain plan (Opus, medium) |
|---|---|---|---|---|
| key_b | 197 | finding on key B + fallback | 3/3 PASS | 2/2 PASS |
| cash_locked | 232 | cancel the outbid bids, free the cash | 3/3 PASS | 2/2 PASS |
| announce_429 | 215 | back off / announce at most every 20 ticks | 2/2 PASS | 2/2 PASS |
| goal_freeze | 240 | allow small value deals while saving | 3/3 PASS | not graded: API timeout at 60 s |
| team5_ret01 | 273 | accept #4167 | 3/3 PASS | 1/1 PASS |
| outlier_asks | 268 | cancel #4117/#4144 and flag the unknown actor | 3/3 PASS | 2/2 PASS |
| ret_no_score | 300 | avoid_buy_sets RET | 2/2 PASS | 1/1 PASS |
| mal_goals | 230 | goals MAL-09/10 at <= 90 P | 3/3 PASS | not graded: API timeout at 60 s |
| t12_carmen | 230 | rival analysis of Team 12 | 3/3 PASS | not graded: API timeout at 60 s |
| new_dealer | 263 | re-plan for Pilar: unlock path | 2/2 PASS | not graded: API timeout at 60 s |
| probe_refused | 212 | finding on the broker probe bug | 2/2 PASS | 1/1 PASS |

**Result:** all 11 detections pass in code. 7 of 11 brain decisions are graded and all 7 are correct. 4 (goal_freeze, mal_goals, t12_carmen, new_dealer) could not be graded: each request hit the 60 s API timeout (Opus at medium effort takes 50-60 s on this prompt) and the approved budget was used up by the re-asks and the 3 successful plans, so they were not retried.

**Avoid-set contradictions:** gone. The 3 new plans (key_b, probe_refused, announce_429) passed the code-side sanity check with no validation errors (avoid_buy_sets = LAT). In the earlier run every plan had "post_offers wants LAT-07/SAL-10/... a set we avoid".

## What the brain side still needs

1. **Timeout for the brain's own calls.** The eval runner uses the client default `DEFAULT_TIMEOUT_S = 60` (`bazaar/llm/client.py`), and 4 of 7 brain plans timed out at 60 s (the successful ones took 49-59 s). The live strategist did not hit this (47 ok plans in the last 2 h, its 3 errors were key B 400/401), but the margin is thin. Fix: pass a per-purpose timeout of about 150 s for purpose `strategy` / `brain_eval` (council can stay at 60 s), and in the eval runner give `ask()` a deadline of 150 s.
2. Re-run the 4 ungraded scenarios once the timeout is raised (about 0.9 $).

## key_b · Key B answers every call with 400 (no workspace); bot falls back to code
Tick 197 · expected: finding on key B + fallback
- code PASS: llm_health counts key B errors
- code PASS: anomaly names key B
- code PASS: idle cause: decisions from code fallback
- plan PASS: plan flags key B failing
- plan PASS: plan notes the code fallback
- top priorities: Free the cash: cancel bid 2760 (40 P at 40, MAL-09 sells at 77 from Chato, t17 bids 70) and ask 3260 (MAL-02 at 10 P, worth 1.3 to us, other | Take t12's 8 P bid for our spare LAV-04 (offer 5143, worth 4 to us, +4); cancel swap 3085, which gives the same card | Swap SAL-07 (22.5 to us) for t01's SAL-10 (63 to us), +40.5. Cancel 3261 so the card is free to post

## cash_locked · 51 P parked in cash bids (MAL-09 40 P outbid by 70 P, RET-06 11 P): 0 P dealer budget
Tick 232 · expected: cancel the outbid bids, free the cash
- code PASS: cash locked in bids >= 40 P
- code PASS: idle cause names the locked cash
- code PASS: outlier: our MAL-09 bid is outbid

- plan PASS: cancels the outbid cash bid(s) — `cancel [3259, 3628, 3659] outbid [3628]`
- plan PASS: explains cash is parked/locked
- validation errors: ['post_offers wants LAT-07, a set we avoid']
- top priorities: Cancel bid 3628 (MAL-09 at 40, outbid by t17 at 70). This frees 40 P; cash goes from 26 free to 66. | Raise cash for MAL-09 or MAL-10 (worth 91 each, Chato list 77, goal 88). Sell spare MAL-07 (value 8.1) to t13 for 22: t13 paid t17 25 for on | Swap SAL-07 (22.5) to t01 for SAL-10 (63), a +40.5 P gain. There is a rastro bid for SAL-10 at 78, so we could later resell it for +15 more.

## announce_429 · Broker announcement refused every tick (one per venue per 20 ticks)
Tick 215 · expected: back off / announce at most every 20 ticks
- code PASS: refusals count broker_announce 429s
- code PASS: recent_refusals show the rate-limit text
- plan PASS: plan addresses the refused announcement
- plan PASS: plan respects the 20-tick limit / backs off
- top priorities: Cancel bid 2760 (40 P for MAL-09, outbid by t17@70) to free 40 P. Then buy MAL-09 from Chato: open at 70, max 85 (worth 91, list 77). Then M | Accept t12 bid 5143: 8 P for our spare LAV-04 (worth 4 to us, +4 P). Cancel swap 3085, which offers the same LAV-04. | Swap SAL-07 (22.5 to us) to t01 for SAL-10 (63): +40.5 value. Cancel 3261 (SAL-07 ask) first.

## goal_freeze · Goal mode froze every trade (ticks 224-240 with 0 actions)
Tick 240 · expected: allow small value deals while saving
- code PASS: ticks without actions >= 10 of last 20
- code PASS: idle cause names the goal saving
- code PASS: goals in force are MAL-09/MAL-10
- plan: not run

- plan: not graded (API timeout at 60 s in the eval run)

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
- code PASS: outlier detector flags #4117 (RET-06 at 55 P, value 27.5)
- code PASS: outlier detector flags #4144 (RET-01 at 40 P, value 11)
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

## mal_goals · MAL-09/MAL-10 worth 91 P complete Malasaña
Tick 230 · expected: goals MAL-09/10 at <= 90 P
- code PASS: automatic goals MAL-09/10
- code PASS: goal prices below value (<= 90)
- code PASS: picture shows MAL-09/10 worth ~91
- plan: not run

- plan: not graded (API timeout at 60 s in the eval run)

## t12_carmen · Team 12 scores buying El Retiro from Carmen below value
Tick 230 · expected: rival analysis of Team 12
- code PASS: rival research covers t12
- code PASS: t12 RET buys seen
- code PASS: t12 partner is abuela
- plan: not run

- plan: not graded (API timeout at 60 s in the eval run)

## new_dealer · A new dealer (Doña Pilar, L3) is announced and goes active
Tick 263 · expected: re-plan for Pilar: unlock path
- code PASS: event detector reports the new dealer pilar
- code PASS: picture lists pilar with unlock rules
- plan: not run

- plan: not graded (API timeout at 60 s in the eval run)

## probe_refused · Market Test probe refused: price must sit between the ask and the bid
Tick 212 · expected: finding on the broker probe bug
- code PASS: picture shows the Market Test probe refusal
- code PASS: picture carries the broker's Market Test status
- plan PASS: finding on the broker probe bug
- top priorities: Free cash: cancel bid 2760 (40 P for MAL-09; t17 bids 70, so it will not fill). Cash available goes from 11 P to about 51 P. | Accept t12 offer 5143: 8 P for our spare LAV-04 (worth 4 to us, +4 P). Cancel 3085, which offers the same card. | Post SAL-07 to t01 for SAL-10 (22.5 -> 63, +40.5 P) on v07, so the fill counts on our venue.
