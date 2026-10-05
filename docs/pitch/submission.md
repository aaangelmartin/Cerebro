# Submission to the judges

The text we prepared for the "Submit your project" form of The Bazaar · Cromos de Madrid (Causa Prima hackathon, Madrid, 2 to 4 October 2026). The judges' round was 40 of the 100 points. The form takes plain text, so the long section uses capital-letter headings instead of Markdown.

## Project name

Cerebro. Smart money in every deal.

## Pitch

Cerebro is smart money in every deal: an agent that trades, negotiates and duels on its own, and a market we built for everyone else's agents.

How we approached it. Our first idea was to let one strong model play. On Friday the dealers lied to it and other teams tried to talk it into bad trades. A prompt cannot be trusted with money, so we changed the rule: the model proposes, the code disposes.

What we built. Cerebro, a strategist that writes policy in plain language. A fast loop that acts every tick. Rails in code that veto any move that loses value. A council of three opinions for the big moves. A recorder, a lab that tunes the agent on our own recordings, and a workshop where it repairs itself while it plays. And v07 Market, a market outside the Bazaar with private matching on limits nobody sees and auctions with a sealed reserve.

Why this way. Every safeguard lives in code, because code cannot be talked out of it. Every change is tested against the recorded game before it goes live. And a human keeps the big calls.

What we learned. Technically: price and delivery days are one package, and you only know your score if you can recompute the game. About negotiation: most deals still started with two people talking, and many bots ignored offers. About marketplaces: a product needs distribution as much as design.

Second of 18 on the final board.

## How it works

```text
THE IDEA

Friday. First idea: let the model play. One strong model read the state and wrote every message and every offer. It took one evening to see the problem. Dealers lie, prompt injection is legal in this game, and a model that can be talked into a bad price will be. A prompt cannot be trusted with money.

Saturday. What changed it. We split the work. A strategist thinks slowly and writes policies. A fast loop executes them every tick. Rails in code decide whether an action may leave the building. Around that we added a council for the big moves, a lab that learns from our own recordings, a workshop that repairs code, and a broker for our venue.

Sunday. We opened v07 Market to other teams' agents, and fixed two flaws in the duel logic while the game was running.

Three rules held for three days:

1. The model proposes, the code disposes.
2. Record everything, recompute everything. Every claim we make about the game comes from our own recording of it.
3. A human keeps the big calls.

SYSTEM MAP

Cerebro is not a pipeline. It is a set of parts that pass each other specific things.

Part: What it does. What it passes on
Recorder: Read-only copy of the whole game: feed, books, catalog, leaderboard, clock. Events and cuts, to everyone
Signals watcher: Diffs the rules and the game API, reads news and announcements. Alerts to the strategist and to us
Cerebro (strategist): Reads the state every few minutes, keeps numbered policies in plain language, answers us in chat. Policies and goals, to the fast loop
Council: Three opinions in parallel on a big move or a big change of plan. A majority vote: go, or hold
Fast loop: Runs every tick: perceive, decide, act. Proposed actions, to the rails
Rails: Deterministic checks in code. A veto or a pass
Executor and gateway: The only door to the game. Adds the team key, rate-limits, and one STOP file halts every write. Orders to the game
Duels engine and guard: Prices every package of price and delivery days. Offers and accepts that cannot lose
Fair broker: Matchmaker of our venue, used in the Market Test. Crossed pairs
Lab: Replays recordings, tests lessons, never writes to the game. Lessons, through a gate
Workshop: Turns the agent's own tickets into tested code changes. Fixes, deployed while the bot runs
Dashboard: Every decision, what it cost, and every switch. What the humans need to decide
v07 Market: A market for other teams' agents, settled on our venue. Matches
Human in the loop: Two people. Policy, approvals, caps

One supervisor keeps the processes alive and restarts any that dies.

ONE TICK, STEP BY STEP

1. Perceive. The loop reads our hand, cash, open offers, threads and duels. Slow reads rotate so a tick never starves, and the event-triggered ones are skipped while a duel is live.
2. Decide. Policies become concrete actions: a bid at a goal price, an offer addressed to one team, a reply to a dealer. Frequent, cheap text (haggling, team chat) goes to a fast model. Strategy goes to a stronger one. Duels get a model bounded by code.
3. Deadline. Every model call has a deadline and a code fallback. A timeout never leaves a tick unanswered. A late answer can serve the next tick if nothing moved.
4. Rails. Every write passes the checks below.
5. Act. The gateway sends it, and the recorder sees the result come back in the public feed.

RAILS: WHAT CODE VETOES, AND WHY

Why code and not a prompt: the other side of every conversation is trying to change our mind, and it is allowed to.

- Value. Each trade is priced at our private value, with copy marginals and page bonuses. A trade that loses value is refused unless a human authorises that one trade.
- Protected cards. Nothing from a complete page can be sold, swapped or crafted. Selling one card breaks the page.
- What the offer delivers, not what the dealer says. Los Pícaros described one card and attached another several times on Sunday. All refused, and flagged.
- Hard switches. No sealed packs. Caps per deal and per hour. Blocked teams and venues. A floor price per card that also blocks accepting a bid below it.
- External text is data. Dealer replies, other teams' messages and announcements are never treated as instructions.

On Sunday the rail refused to buy an epic at 149 because we valued it at 126. It was right by its own rule. A human then authorised that purchase, because a team was waiting to pay more for it. That is the division of labour we wanted.

CEREBRO AND THE COUNCIL

Cerebro keeps policies as short numbered sentences, for example: "this epic only to teams, floor 228, never on our own venue", or "when a human sets a target price, that is the price: do not accept the buyer's first number". Policies are written in plain language so we can read them, challenge them in chat and overrule them. When two of us gave clashing instructions, it kept both, said which one won and why.

The Council is three opinions asked in parallel. A big move inside the tick, or a big change of plan, goes ahead only with a majority. If it is vetoed, the move is held.

DUELS

A duel is a short bargaining game on price and delivery days, with a pie that shrinks every round. The engine computes the exact result of every package for us (price and days, with that duel's own weight and sign), opens by a schedule, and accepts when waiting is worth less than what is on the table. A model writes offers inside a range set by code. A guard corrects the days of any offer and blocks every package that loses once days are counted. If the model is late, code answers.

Closed with a deal: 60 of 68 on Saturday, 59 of 68 on Sunday morning, 23 of 34 in the Final. No duel left unanswered.

THE LAB: TUNED ON OUR OWN RECORDINGS

The lab is a separate process that never writes to the game. It replays recorded sessions, proposes lessons, and tests each one three ways: backtest, simulation and shadow run. A gate in code moves a lesson from proposed to shadow to canary to active, or retires it. It also tuned the broker for the Market Test. This is not model training. It is the system adjusting its own parameters and rules against what actually happened.

THE WORKSHOP: SELF-REPAIR UNDER A HUMAN GATE

When the agent sees itself misbehave, it files a ticket: evidence, diagnosis, proposed change. A coding agent makes the smallest change with tests. Protected paths (rails, executor, model code, config) need a human Accept. The full suite runs before deploy, and a failing suite reverts the change. The bot keeps playing the whole time.

HOW WE CAUGHT THE SIGNALS

- Recompute the score. We rebuilt the leaderboard from recorded events and found where the game's scoring did not match its rules. We reported it to the organisers with ticks, settlement ids and numbers.
- Recompute our own deals. An audit agent recalculated every duel with delivery days and found that three had closed at a loss. Our own monitor had only looked at price.
- Watch the rules. A watcher diffs the rulebook and the API and tells us when something changes.
- News, true and false. Some news changed a dealer's behaviour and some was rumour. We checked each against what dealers then did.
- Lore. We found the five claimable easter eggs by reading what each dealer cares about and saying the right piece of Madrid to the right one.
- Bridges. By reading who bid for what, we bought an epic from a dealer and sold it to a team that valued it more, three times.

HUMAN IN THE LOOP

What a person decides: policy, in chat. Accept on protected code. Caps and vetoes. On and off. The price and venue of large sales. Any single trade that loses value.

What the agent decides alone: everything inside those lines, every tick.

V07 MARKET, BRIEFLY

https://market.nglmrtn.com · code in bazaar/plaza/

A market for other teams' agents, built on our venue (v07, 0% fee). It has more than two sides: sellers, buyers, their agents, and our broker, which proposes and never trades.

- Connect without a key. The agent gets a short code and sends it to us in a game thread. Only the real team can write as that team, so the thread proves who it is. We never see anyone's game key.
- Private sheet. What the agent holds, what it wants, and its private limits per card.
- Blind overlap. The matcher asks one question: do the two limits overlap? It proposes a trade only when both sides gain.
- Price. Inside the overlap, on a price grid, never the midpoint and never equal to a limit, so nobody can infer the other side's number.
- Settlement. The market never holds cards or cash. The trade is an offer on v07 in the game, and a match counts only when our recorder sees that settlement in the game's public feed.
- Also: auctions with a sealed reserve, private hidden-demand signals, one warning and then removal for a matched deal taken to another venue, and one AGENTS.md that describes the whole API.

Limits are stored encrypted, apart from the rest of our stack. This is access control on our machine, not a cryptographic proof.

HOW WE BUILT IT

Many coding agents in parallel, each owning its files and committing only those. One thread talked to the humans and decided; the rest executed. Independent agents reviewed the market's security cold, four times. Tests gate every deploy.

WHAT WENT WRONG

- We gave away delivery days. As buyer the agent offered ten days when each day cost us, because the guard checked price only. Three duels closed at a loss. We found it live, switched to code-only decisions in minutes, shipped a fix with regression tests, restarted once and missed no duel.
- The Final, seen too late. The agent accepted one tick late against rivals that conceded on the last tick, and it refused packages that were profitable once days were counted, because an older rule looked at price alone. We found it with too few duels left to ship a fix safely.
- A rule that became a wall. "Never lose value" protected us for two days. On Sunday the teams that scored made a few large trades with each other, and our rule kept us out until a human stepped in.
- We sold on a rival's venue. One sale settled on a rival venue and gave that team the market points. A constraint that matters must be in code, not in someone's head. Today it is a policy; it should be a rail.
- A market few teams used. One team verified its agent, one third-party trade settled on v07, and one team listed its spare cards there. Many teams were not fully automated: their bots ignored offers and messages, and a deal only started when two people talked at a table. We built for agents and the room still ran on people.

NUMBERS

- 2nd of 18 on the final board: 35.76 of 60 server points. First when Saturday closed.
- Duels closed with a deal: 60 of 68 (Saturday), 59 of 68 (Sunday morning), 23 of 34 (Final). None unanswered. None at a loss after the fix.
- Sunday trades with teams: three dealer-to-team bridges (+27, +26, +5) and one epic sold at 216 (+18).
- 1,602 automated tests. 441 commits when we counted on Sunday afternoon.
```

## What would you do with one more day?

1) Score the trade, not the card. Our rails price each trade at our private value and refuse anything negative. The game rewards value gained in team trades up to a cap, the last card of a page, and trades that happen on your venue. With one more day the rails would optimise expected table points, with "never lose value" as one input and not a wall.

2) Make venue a first-class decision. On Sunday, where a trade settled moved more points than the trade itself. The executor should choose the venue by who it helps and refuse a rival's venue in code.

3) Give the model the whole tick. Read the game state in parallel so a duel offer always has time to be written, and check live that every model-written offer went through the guard. Ship the two duel fixes we found in the Final: accept on the package with days, and close one tick earlier.

4) Close the self-repair loop. Today the agent files tickets and a coding agent fixes them with a human at the gate. Next: shadow-run each fix on the recorded day before it goes live.

5) Take the market to where deals start. Teams did not finish connecting because a person had to carry a prompt to their agent, and most deals began with two people talking. We would post the offer where agents already read, in game threads and announcements, with the exact call to make, and walk the room with it.

6) Publish the recorder and the replay as a kit. Most of what we learned came from being able to recompute the game. The weekend is better if every team can.

## Links

| Label | URL |
|---|---|
| Repository | https://github.com/aaangelmartin/Cerebro |
| Video: how Cerebro works (narrated, 3 min) | https://nglmrtn.com/Cerebro/video/ |
| Pitch deck (animated) | https://nglmrtn.com/Cerebro/pitch/ |
| Pitch deck (PDF) | [cerebro-pitch.pdf](cerebro-pitch.pdf) |
| Cerebro Dashboard (frozen snapshot, read-only) | https://nglmrtn.com/Cerebro/ |
| v07 Market (live while our machine is on) | https://market.nglmrtn.com |
| AGENTS.md (what an agent reads) | https://market.nglmrtn.com/AGENTS.md |
