# Broker vs the free stall: findings and plan (Sat 3 Oct, updated 12:30)

## Results so far

| Session | Our efficiency | Stall (replay) | Difference | Bench points |
|---|---|---|---|---|
| b7 (h3.0) | 0.899 | 0.892 | +0.007 | 0.5 |
| b25 (h5.0) | 0.933 | 0.931 | +0.002 | 0.5 |

Rules: matching as well as the free stall earns half the bench points; full points go to the mean of the top three venues. We are at stall level in both sessions.

## Why we are not above the stall

- **The rule is "quotes"**: the server only accepts a match priced between the ask and the bid, so only pairs whose quotes already cross can trade. The stall crosses every such pair at once.
- **Real traders are short-lived.** In b7, 20 traders arrived one by one over 12 ticks; 11 of them were visible for a single tick, and the unmatched ones left after 1 to 5 ticks. Waiting for a better pairing rarely pays.
- **Every crossing pair in b7 was matched** the tick it appeared. The value lost came from pairs that never crossed in time (e.g. buyer b7-1 at 79 and seller b7-16 at 80, one step apart when the buyer left).
- **Little room even with perfect information.** An oracle that knows every hidden limit beats the stall by only 1 to 2 points of efficiency in the simulator (normal 0.919 vs 0.908, hard 0.870 vs 0.847, fitted-to-real 0.541 vs 0.535). The engine is already between the two (normal 0.909, hard 0.863).

So "much better than the stall" is not available from matching alone under this rule. The realistic gains are small edges, plus the other half of the market score: value created between other teams on our venue (public trades on v07).

## Changes made

- **Quotes rule from the start, no probes** (commit 005369e, deployed before b25; `data/lab/broker/policy.json` set to `cross_rule: quotes`). Level or better in every sim profile: normal 0.9090 vs 0.9089, hard 0.8626 vs 0.8596, real 0.5361 vs 0.5341.
- **`sim_book.REAL`**: a profile fitted to the real session (lifetimes are still too short in it: it gives 0.53 where real sessions give 0.90; refit `life` from b7 and b25).
- **The brain sees each session vs the stall**: `research.broker.sessions_vs_stall`.

## Learning loop (built, committed, NOT deployed: needs restarts between sessions)

- **Overlay** `data/live/broker_policy.json`, validated with hard bounds (`bazaar/broker/policy_overlay.py`). The broker reads it only when no session is running and logs `policy_version` in each session's start record, stats and heartbeat. Tested, including "no change mid-session".
- **Brain**: `broker_policy` (+ `broker_policy_why`) in its plan, validated, always a council vote; when accepted it writes the overlay. Its research shows the overlay, the policy version in use and the Lab's broker lessons.
- **Lab** (`bazaar/lab/broker_learn.py`): reads the sessions, tries a grid of overlays in the simulator against the policy in use and proposes the best as a `broker` lesson with its predicted delta. **Not wired into the Lab cycle and has no tests yet.**

## Update 12:30: overlay live, Lab wired, simulator refitted

- **Deployed between sessions (12:03, no session running):** broker and strategist restarted with the overlay code. No `broker_policy.json` exists, so the policy in use is unchanged (quotes rule, no probes).
- **Lab wired:** `Lab.cycle` calls `learn_broker()`: never while a session runs, at most every 2 minutes, and it only works when a new session has finished. It costs no API calls (0.2 s per policy in the simulator). The gate leaves `broker` lessons that carry `params.broker_policy` to el cerebro. Tests in `lab/tests/test_broker_learn.py`.
- **`sim_book.REAL` refitted from b7 and b25:** stall 0.915 in the simulator (real 0.892 and 0.931), 9.5 of 20 traders matched (real 8 to 10), 38 % seen for one tick (real 45 %), unmatched traders visible 3.2 ticks (real 3.2). What made the fit work: quotes start close to the limits, and traders with no chance at the going price leave after 1 to 5 ticks while the others stay.
- **Grid rerun on the refitted profile (200 to 300 sessions each):**

| Profile | Stall | Engine | Oracle |
|---|---|---|---|
| normal | 0.908 | 0.909 | 0.919 |
| hard | 0.847 | 0.863 | 0.870 |
| fitted to real | 0.904 | 0.894 | 0.904 |

  On the real-like profile the engine is 0.006 to 0.010 below the stall, and even the oracle only equals it. No overlay wins clearly: the best (`prior_shade` 0.05) gains 0.006 on the real profile and loses 0.003 on hard; `wait_ticks`, `hazard`, `endgame_ticks`, `firm_ticks` and `tt_bonus` change nothing. **So no policy change is deployed.** In the two real sessions we were 0.007 and 0.002 above the stall replay.

## Remaining

1. Done (12:03).
2. Done.
3. Done: no overlay wins clearly.
4. Replay the recorded sessions (book per tick) as a backtest for lessons, not only the synthetic simulator.
5. Conflict choice when one seller crosses two buyers: test "leave the pair closest to crossing" against "highest bid first" on replays.
6. The larger lever: public trades on v07 (other half of the market score): more teams listing publicly there.
