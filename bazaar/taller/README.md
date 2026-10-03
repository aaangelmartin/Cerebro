# El taller

Turns el cerebro's code requests (outbox items of kind `code`) into tested, pushed and deployed changes. The code is written by a **fork of the main Claude Code conversation** (the user's Claude subscription), started from a `/loop` in that session. The taller hands out the work and closes it safely. Humans only press **Aceptar** for the gated requests.

## Policy (chosen by the team, Saturday 3 Oct)

**Auto + deploy if the tests pass.**

- **Auto:** low or medium severity requests that don't touch money, rails or keys. Handed out while `open`.
- **Gated:** critical severity, or anything about rails, the executor, cash, caps, never-lose, the LLM keys or router, or `.env`. Handed out only after someone sets the item to `accepted` (dashboard: Cerebro → Para el equipo → Cambios de código → Aceptar).
- `--finish` checks again on the files the commit really changed. A commit that touches `bazaar/core/rails.py`, `bazaar/core/executor.py`, `bazaar/llm/`, `bazaar/config.py` or `.env` without acceptance is reverted locally (nothing is pushed) and parked as "pulsa Aceptar".

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
   - errors → `git revert`, push, restart, item `rejected` with the errors; clean → item `done` with the commit.
5. **If the request is wrong or impossible:**
   ```bash
   .venv/bin/python -m bazaar.taller.run --fail <id> --reason "why"
   ```

A request the taller already handled is handed out again only when a human sets it to `accepted` afterwards. Every step goes to `data/live/taller.jsonl`; the state is in `data/taller/state.json`; one job at a time (`data/taller/lock`).

## Older headless mode (not used)

`--once ID` and `--loop-claude` run `claude -p` in an isolated worktree with restricted tools. They strip every API key and provider switch from the environment so Claude Code runs on the logged-in subscription, but the team chose forks of the main conversation instead, so nothing runs them.
