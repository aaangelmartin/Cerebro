# Live narration for the silent cut

The silent cut of the video (2:38) has no audio and no subtitles: we talked over it on stage. The section name and a clock sit in the top right corner, and a progress bar by section runs along the bottom. Each line below is one shot; the time code is the one in the silent cut.

## One line per section

- **0:00–0:09 · Opening**: Cerebro, by Team 10 · smart money in every deal
- **0:09–0:45 · The agent loop**: The agent loop: recorder → lab → tick → strategist → fast loop → rails
- **0:45–0:59 · Duels: pricing the days**: Duels: we price the whole package, Claude bounded by a guard
- **0:59–1:14 · Self-repair workshop**: Self-repair: request → agent → tests → live deploy
- **1:14–1:29 · The dashboard · the broker**: One dashboard; the human only sets limits; our broker runs the Market Tests
- **1:29–2:12 · v07 Market**: v07 Market: connect without keys, blind overlap matching, settles in the game
- **2:12–2:22 · How we built it**: Built the same way: parallel Claude agents, one owner per file, 1,602 tests
- **2:22–2:38 · Lesson and one more day**: Lesson: distribution. One more day: take the market to the teams

## Shot by shot

### 0:00 → 0:09 · Opening
- `0:00` This is Cerebro, by Team 10: smart money in every deal. Our agent trades and we build.
- `0:06` Here is what we built and how it works inside.

### 0:09 → 0:45 · The agent loop
- `0:09` A recorder captures every event, tick by tick, so we can replay any decision.
- `0:16` A lab mines those recordings for lessons, backtests them, and a gate in code promotes only what holds up.
- `0:23` Every tick the bot reads the state: album, cash, every open offer.
- `0:28` A strategist on Claude writes policies in plain language.
- `0:32` A fast loop turns them into actions.
- `0:35` Rails in code check every action: a buy above our own value is vetoed, whatever the model says.
- `0:42` The model proposes, the code disposes.

### 0:45 → 0:59 · Duels: pricing the days
- `0:45` Duels are negotiations against the clock: price and delivery days.
- `0:49` Each day is worth points, so we value the whole package.
- `0:54` Claude proposes, a guard in code corrects, and plain code answers if the model is late.

### 0:59 → 1:14 · Self-repair workshop
- `1:00` When something breaks, the strategist files a request.
- `1:02` An agent writes the fix, runs the suite and deploys while the bot keeps playing.
- `1:07` Sunday's delivery-days bug was found, fixed, tested and live in minutes.

### 1:14 → 1:29 · The dashboard · the broker
- `1:14` One dashboard shows everything: feed, album, market, duels, oversight.
- `1:21` We set limits and switches; the agent does the rest.
- `1:24` In every Market Test our own broker matches the crossing pairs on our venue.

### 1:29 → 2:12 · v07 Market
- `1:29` Then we built something outside the Bazaar: the v07 Market.
- `1:33` An agent connects with one prompt and proves its team with a code in a game thread. We never ask for a key.
- `1:40` It publishes a private sheet: what it has, what it wants, its limits.
- `1:44` The matcher asks one blind question: do the limits overlap?
- `1:48` The price lands inside the overlap; no team ever sees a limit.
- `1:51` The trade settles in the game and counts only when the game's feed shows it. We never hold cards or cash.
- `1:59` Auctions with a sealed reserve, and private signals of hidden demand.
- `2:03` Take a matched deal elsewhere: one warning, then removed.
- `2:08` And one file, AGENTS.md, lets any agent run all of it.

### 2:12 → 2:22 · How we built it
- `2:12` We built it the same way: many Claude agents in parallel, each owning its files.
- `2:18` Repeated security reviews and 1,602 tests behind it.

### 2:22 → 2:38 · Lesson and one more day
- `2:23` The lesson: few teams used the market. Distribution matters as much as design.
- `2:28` With one more day we would bring the market to the teams.
- `2:31` Cerebro, by Team 10. Smart money in every deal.

Total: 388 words in 2:38. If you are running short, skip the "tick", "fast loop" and "auctions" lines.
