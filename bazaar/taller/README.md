# El taller

Turns el cerebro's code requests (outbox items of kind `code`) into tested, pushed and deployed changes, using Claude Code in headless mode. Humans only press **Aceptar** for the gated ones.

## Policy (chosen by the team, Saturday 3 Oct)

**Auto + deploy if the tests pass.**

- **Auto:** low or medium severity requests that don't touch money, rails or keys. The taller takes them while they are `open`.
- **Gated:** critical severity, or anything about rails, the executor, cash, caps, never-lose, the LLM keys or router, or `.env`. They wait until someone sets the item to `accepted` (dashboard: Cerebro → Para el equipo → Cambios de código → Aceptar).
- The check runs twice: on the request's text before starting, and on the files Claude actually changed. A change that touches `bazaar/core/rails.py`, `bazaar/core/executor.py`, `bazaar/llm/`, `bazaar/config.py` or `.env` without acceptance is parked as "pulsa Aceptar".

## One job

1. Claim the request (note `taller: en curso`), take the lock `data/taller/lock` (one job at a time).
2. New git worktree from `origin/feat/bazaar-v2` at `data/taller/wt-<id>`, branch `taller/<id>-<slug>`. The main working copy is never touched while Claude works.
3. `claude -p` in the worktree, with only Read, Edit, Write, Grep, Glob and Bash for the unit tests and `git diff/status`; at most $4 and 20 minutes per request. The game's API keys are removed from its environment.
4. The full test suite in the worktree. Red → the request goes back to `open` with the reason.
5. Commit (Conventional Commits, message written by Claude, `Co-Authored-By` trailer), rebase on the latest `feat/bazaar-v2`, tests again if it moved, push the branch and fast-forward `feat/bazaar-v2`. Never force, never `main`.
6. Update the local copy with `git pull --ff-only` when the touched files have no uncommitted changes; otherwise the item says "pendiente de integrar en la copia local" and nothing is restarted.
7. Restart only the affected services (bazaar.supervise starts them again) and watch their logs for about three ticks. New errors → `git revert`, push, restart, item `rejected` with the errors. Clean → item `done` with the commit.

Every step goes to `data/live/taller.jsonl`; the heartbeat is `data/live/taller_status.json`.

A request the taller already handled runs again only when a human sets it to `accepted` afterwards.

## Commands

```bash
.venv/bin/python -m bazaar.taller.run              # the loop (polls the outbox every 60 s)
.venv/bin/python -m bazaar.taller.run --dry-run    # what it would take now
.venv/bin/python -m bazaar.taller.run --once <id>  # one request now (same policy)
```

It runs under `bazaar.supervise` as the service `taller` (logs in `data/live/taller.out`).
