# El taller

Turns el cerebro's code requests (outbox items of kind `code`) into tested, pushed and deployed changes. The code is written by a **fork of the main Claude Code conversation** (the user's Claude subscription), started from a `/loop` in that session. The taller hands out the work and closes it safely. Humans only press **Aceptar** for the gated requests.

## Policy (chosen by the team, Saturday 3 Oct)

**Auto + deploy if the tests pass.**

- **Gated:** a request waits for **Aceptar** only when
  - its severity is `critical`, or
  - its change (`proposed_change`, `patch_sketch`, the paths it mentions) names a gated file — `bazaar/core/rails.py`, `bazaar/core/executor.py`, `bazaar/llm/`, `bazaar/config.py`, `.env` — or a money cap or key: `cash_reserve`, `max_spend_per_deal`, `max_spend_per_hour`, `min_surplus`, an API key.

  Handed out only after someone sets the item to `accepted` (dashboard: Cerebro → Para el equipo → Cambios de código → Aceptar).
- **Auto:** everything else, handed out while `open`. Loose words in the text ("cash", "spend", "reserve", "rail", "key") do not gate a request: on 3 Oct that filter held back three requests that touched no gated file.
- **Second net:** `--finish` checks the files the commit really changed. A commit that touches a gated file without acceptance is reverted locally (nothing is pushed) and parked as "pulsa Aceptar", whatever the request's class was.

## Why `--next` gave nothing

`--next` still prints `null` on stdout when there is no work, and now says why on stderr, one line per open request: `id | status | class | severity | reason | title`. `--list` prints the same table and changes nothing. The reasons:

- `eligible (auto|accepted)`: it will be handed out.
- `gated: <what it names> (Aceptar to run it)`.
- `another job running: claimed by a fork since HH:MM (released in N min)`.
- `handled at HH:MM (failed|rejected|needs_accept…): Aceptar to run it again`.
- `possible duplicate: done in <commit> at HH:MM and filed again`.

"another taller job is running: --finish <id> since HH:MM:SS (pid N)" (exit code 1) means another `--next` or `--finish` holds the lock right now; a `--finish` takes a few minutes (tests, push, restart, watch). A `--next` should try again on the next loop; a `--finish` waits for the lock by itself (up to 20 minutes), so two deploys never overlap.

## Claims, parallel work and duplicates

- **Several forks can work at once.** The lock only serialises the `--next` and `--finish` commands themselves; each `--next` claims a different request. The taller does not check that two claimed requests touch different files: each fork commits only its own paths, and `--finish` tests each commit on a clean checkout.
- **A claim expires.** A request claimed more than 25 minutes ago with no `--finish` or `--fail` is released on the next `--next` (note "liberado", back to `open`, or to `accepted` if a human had accepted it) and handed out again. A fork that needs longer should `--fail` and reclaim, or finish first.
- **Possible duplicates.** When el cerebro files a request whose title matches one already done, the outbox reopens the old item. If that happens within 2 hours of the fix, the taller notes "posible duplicado" and does not hand it out on its own (Aceptar runs it now). After 2 hours it is taken again: the fix did not hold.

## The procedure a fork follows

1. **Take the next request:**
   ```bash
   .venv/bin/python -m bazaar.taller.run --next
   ```
   Prints `null` when there is nothing to do. Otherwise a JSON with `id`, `class` (auto or gated), `title`, `diagnosis`, `evidence`, `proposed_change`, `patch_sketch`, `impact`, the paths it mentions and the processes they would restart. The item is now claimed ("taller: en curso (fork)").
2. **Implement it in the main working copy**: the minimal change plus unit tests. Run the suite: `.venv/bin/python -m unittest discover -s bazaar -t .`
3. **Commit only your files** (`git add <paths>`, never `-A`, never stash), with a message file: Conventional Commits, mention the request id, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Don't push.
4. **Close it:**
   ```bash
   .venv/bin/python -m bazaar.taller.run --finish <id> --commit <hash>
   ```
   - runs the full suite on a clean checkout of that commit (red → reverted locally, item back to `open`);
   - pushes `feat/bazaar-v2` (never force, never `main`; if origin moved it answers `push_failed`: `git pull --rebase origin feat/bazaar-v2` and `--finish` again with the new hash);
   - restarts only the affected processes (bazaar.supervise starts them again) and watches their logs for about three ticks;
     a process that is missing at the end of the watch is re-checked for up to 45 s before it counts as down, so somebody else restarting it at that moment does not revert a sound commit;
   - errors → `git revert`, push, restart, item `rejected` with the errors; clean → item `done` with the commit.
5. **If the request is wrong or impossible:**
   ```bash
   .venv/bin/python -m bazaar.taller.run --fail <id> --reason "why"
   ```

A request the taller already handled is handed out again only when a human sets it to `accepted` afterwards (or, for a done one filed again, 2 hours after the fix). Every step goes to `data/live/taller.jsonl`; the state is in `data/taller/state.json`; one `--next`/`--finish` command at a time (`data/taller/lock`).

## Older headless mode (not used)

`--once ID` and `--loop-claude` run `claude -p` in an isolated worktree with restricted tools. They strip every API key and provider switch from the environment so Claude Code runs on the logged-in subscription, but the team chose forks of the main conversation instead, so nothing runs them.
