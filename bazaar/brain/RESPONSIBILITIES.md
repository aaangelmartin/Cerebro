# El cerebro: responsabilidades (todo lo que hoy decidieron los humanos)

Every item below was decided by the humans or the main session on Saturday morning. From now on el cerebro decides each one by itself, with data, and applies it; the council (medium effort) votes the big ones; humans are only a hint source via the chat.

## Money, keys and model
1. Spend policy: keep Opus where it pays, watch the day cap and degrade thresholds, spend more when it earns points (duels, dealer haggles).
2. Key health: detect a key that always fails (e.g. B with 400 "not scoped to a workspace"), stop using it and raise a finding; notice when the bot fell back to code.

## Venue, broker and alliances
3. Our venue v07: keep it open, its fee (0 %), broker mode during Market Tests (probe refusals like "price must sit between the ask and the bid" are a bug to fix).
4. Announcements: when and what to announce (rate limit: 1 per 20 ticks per venue), text in the style that works (stats hook + "Just tell your agent: …").
5. Alliances: evaluate and run them (Team 5 / v10: they sell on v07, we sell on v10); answer allies fast; ask them to post publicly on v07 if that scores more; use their tips (price near market).
6. Venue choice per offer (El Rastro 5 % + 1 P taker fee vs allied 0 %; traffic vs fee).

## Prices and trades
7. NEVER lose value on any trade (hard rail in code; the brain must also never propose one).
8. Prices near the live market of each venue, never below our floor (value + margin) for sells, never above value − margin for buys.
9. Close small haggles fast; a dealer's final offer beats a non-urgent duel accept.
10. Packs: buy only when clearly worth it.
11. Accept addressed offers that gain value even if a keep-one rule blocks them (e.g. Team 5's 20 P for our only RET-01 worth 11 P), with council.
12. Cancel/reprice our outlier offers (e.g. RET-06 at 55 P, RET-01 at 40 P); flag offers by t10 not made by the bot (unknown actor on our key).

## Goals and collection
13. Goals: find pages close to complete with valuable missing cards (MAL-09/10 worth 91 P each) and set max prices; save cash for them without freezing everything (small value deals still allowed); no cash parked in bids others outbid.
14. Avoid sets that don't move our score (El Retiro now: "no compres Retiro, no nos suma"), re-checked with data.
15. Which cards we need and which cards other teams need: sell our spares to who wants them, buy what we need below value, mutual swaps, contested cards.

## Rivals, score and events
16. Track every team's score by component (negotiation, market) over time; attribute their gains to actions; a points plan to beat the leader in each component.
17. Investigate leaders' play (Team 12 buying RET from Carmen below value, short negotiations, selling low-value commons; Team 18 leading negotiation) and copy what works for our affinities.
18. Events: new dealer / unlock rules (El Chato, hidden L3), levels, schedule changes (brief, Market Tests, Duels I 11:30, Duels II 18:00 with delivery day 0–10), new sets, new venues, rival score jumps → re-plan at once.
19. Duels: mode (bounded / full / code), the delivery-day sign in Duels II, always answer (unanswered = 0 for both), open with offers the other side can take.

## Self-supervision
20. Detect when the bot is idle and why (cash locked, goal freeze, rails vetoes, refusals, no candidates, LLM errors) and fix it.
21. Hourly self-review: predicted vs realised points and P; lessons; mistakes and the fixes applied.
22. Chat with memory: answer anything about what it did and why, with data; turn human hints into durable policies it re-evaluates.

## Where each item lives in code

El cerebro is `bazaar/strategist/run.py` (process `bazaar.strategist.run`, Opus 5.5, medium effort). Its research is
`strategist/analysis.py`, its files and checks are `strategist/brainio.py`, the shared plan reader is
`brain/strategy.py`, and the domains apply the plan every tick.

| # | Decision type / check | Code | Test |
|---|---|---|---|
| 1 | `research.llm_health.spend_today/by_purpose`, own day cap `BAZAAR_STRATEGY_DAY_CAP_USD` | analysis.llm_health, run.DAY_CAP_USD | test_analysis |
| 2 | `research.llm_health.anomalies` (key errors vs ok, dead keys); router drops keys the API rejects | analysis.llm_health, llm/client._classify | test_analysis, test_llm |
| 3 | `guidance.broker`, `research.venues`, broker refusals in `research.our_bot.refusals` | analysis.venues/idle | test_analysis |
| 4 | `guidance.broker` (announcements); bot backs off 20 ticks after a refused announce | run.py `announce_retry_tick` | - |
| 5 | `research.our_venue_flow_last_2h`, `allies`, `post_offers` with `to`/`venue` | analysis.venue_flow, Strategist._allies | - |
| 6 | `post_offers.venue`; market `choose_venue` | market/domain | - |
| 7 | hard rail `rail_value` (+1 P minimum, taker fee recomputed, pack EV from the catalog, open_thread) | core/rails.py | test_value_rail, test_never_lose_extra |
| 8 | ask floor value + max(1.5, 5 %), priced at the cheapest live ask / rarity median | market/domain `_market_asks`, `ask_gain` | test_value_rail |
| 9 | `guidance.dealers` | prompt | - |
| 10 | `guidance.dealers`; pack EV rail | core/rails `_pack_value` | test_rails |
| 11 | `accept_offers` + keep-one exception (gain >= 5 P, page <= 50 %), council vote | brain/strategy.keep_one_exception, market `_brain_first`, rails `_brain_exception` | test_analysis.OffersTest |
| 12 | `research.our_offer_outliers`, `research.offers_not_posted_by_our_bot` -> `cancel_offers` | analysis.offer_outliers/unknown_offers, market stale | test_analysis.OffersTest |
| 13 | `goal_buys` (auto < brain < operator), small deals still allowed, cash bids cancelled in goal mode | core/goal.py, dealers/market | test_goal, test_strategy |
| 14 | `avoid_buy_sets` (control + plan, union) + hard rail `rail_avoid_sets`; `research.our_buys_by_set_last_3h.low_impact` | core/goal.avoided, rails | test_goal.AvoidSetsTest |
| 15 | `card_needs` (bazaar.intel.needs) -> `accept_offers`, `post_offers`, `avoid_buy_sets`, goal urgency | Strategist._needs, market `_brain_posts` | intel tests |
| 16 | `research.scoreboard` (components, 1 h/2 h deltas, top gainers) -> `points_plan`, `expected_next_hour` | analysis.scoreboard, brainio.validate | - |
| 17 | `research.rivals_last_2h` (buys/sells vs book, partners, messages per deal) | analysis.rivals | test_analysis |
| 18 | EventDetector (dealers, levels, unlocks, sets, schedule, venues, score jumps, offers to us, novelty) -> run at once | strategist/run.EventDetector | test_strategy.EventDetectorTest |
| 19 | `duel_claude_mode` (council), `guidance.duels` | brain/strategy.overlay | test_strategy |
| 20 | `research.our_bot` (idle ticks, cash locked, goals, vetoes, refusals, fallback share) | analysis.idle | test_analysis |
| 21 | hourly `strategist_reviews.jsonl` (expected vs realised) -> `last_hour_review` in the next prompt; findings topic `self_review` | brainio.hourly_review | - |
| 22 | chat (`/brain/chat`), `chat_reply`, `chat_summary`, `policies` in brain_memory.json, every prompt | brainio, api/server.py | test_strategy.test_chat_round_trip_and_policy |

Quality loop: every plan passes `brainio.validate` (no goal at or above value, goals only on missing page cards, no
avoid-set contradiction, offers must exist, every priority cites a number, points_plan present, as_of_tick fresh);
an invalid plan is re-asked once with the errors, then `brainio.repair` drops what still fails.
