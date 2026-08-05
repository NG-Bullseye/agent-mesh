# Playbook: a standing agent team on a flat subscription

How to go from "the hub is running" to a persistent, self-waking team of
Claude Code agents. Distilled from a production mesh (eight specialist agents,
one host); everything here was shaped by a real incident, not by theory.

## The economics, stated once

A metered-API agent costs money whenever it thinks — so architectures built on
APIs minimize thinking time and die when idle-polling scales. A **subscription
CLI session** inverts that: an open, idle session costs nothing. The design
goal flips from "minimize calls" to "maximize *silence*": agents should be
parked, wake on events, do the work, verify, and go silent again.

## Anatomy of one agent

One agent = one lowercase-kebab slug (`manager`, `dev-agent`, `watchdog`),
used **identically everywhere**: tmux session name, repo directory, cache
paths. Each agent owns a repo with five small parts:

```
~/.local/bin/<name>              → symlink to the launcher (only central artifact)
~/repos/<name>/
  bin/<name>ctl                  1. launcher: attach / fresh-restart, session-id persistence
  bin/ensure-monitors.sh         2. shell-loop init: flock-idempotent, fired by a hook on every prompt
  .claude/settings.json          3. hooks: UserPromptSubmit → ensure-monitors.sh
  CLAUDE.md                      4. the agent's role, rules, and session-init steps
  (optional) .claude/hooks/...   5. extra hooks (auto-compact, guards)
```

### 1. The launcher

A deliberately dumb script: it can `attach` and `restart`, nothing else
(operational logic lives in the session, not in the wrapper):

```bash
#!/bin/bash
set -euo pipefail
NAME="dev-agent"; REPO="$HOME/repos/$NAME"; MODEL="sonnet"
SID_FILE="$HOME/.cache/$NAME/launcher/$NAME.sid"
mkdir -p "$(dirname "$SID_FILE")"; [ -f "$SID_FILE" ] || uuidgen > "$SID_FILE"

start_fresh() {
  local sid; sid="$(uuidgen)"; echo "$sid" > "$SID_FILE"
  tmux new-session -d -s "$NAME" -c "$REPO"
  tmux send-keys -t "$NAME" \
    "claude --model $MODEL --session-id $sid" Enter
  sleep 3
  tmux send-keys -t "$NAME" \
    "Fresh session restart. Read your CLAUDE.md, arm your monitors, then stay silent until a task arrives." Enter
}

case "${1:-attach}" in
  -r|restart) tmux kill-session -t "$NAME" 2>/dev/null || true; start_fresh ;;
  *) tmux has-session -t "$NAME" 2>/dev/null || start_fresh; tmux attach -t "$NAME" ;;
esac
```

The persisted session id means a plain start can `--resume` the previous
context after a reboot; `-r` starts clean when the context should be dropped.

### 2. The two monitor layers (the part everyone gets wrong)

There are two different things people call "a monitor", and only one of them
can wake an agent:

| Layer | What | Can it WAKE the session? |
|---|---|---|
| shell loop | `while true; do … done` started by `ensure-monitors.sh` | **No** — it can only append lines to a log file |
| session monitor | the file-watch the *agent itself* arms at session init | **Yes** — it wakes the session and survives compaction |

The contract: **the shell loop produces the line, the session monitor consumes
it and wakes.** `ensure-monitors.sh` filters whatever stream matters (hub
notify log, journald relay, a heartbeat) into
`~/.cache/<name>/monitors/<topic>.log`; the agent's CLAUDE.md contains a
session-init step like:

> On start, arm a monitor (persistent) on new lines in
> `~/.cache/<name>/monitors/<topic>.log`; on a matching line, wake and handle
> the event.

Two hard-won rules:

- **Don't follow process streams directly** (e.g. `journalctl -f`) from a
  session monitor — under the CLI harness such pipes get killed shortly after
  arming. Relay the stream into a *file* (a tiny always-restart systemd user
  unit) and tail the file; file tails are stable.
- **Clean up monitor zombies.** Compaction/model switches can leave orphaned
  watcher processes behind. Re-arm exactly one monitor per topic and sweep
  orphans on session init.

### 3. ensure-monitors.sh

Idempotent by `flock`, fired by a `UserPromptSubmit` hook so the loops
self-heal on every human/agent interaction with the session — no cron, no
supervisor needed for the light layer:

```bash
#!/bin/bash
LOCKDIR="$HOME/.cache/dev-agent/locks"; mkdir -p "$LOCKDIR"
start_loop() {  # $1=name $2=command
  flock -n "$LOCKDIR/$1.lock" -c "$2" >/dev/null 2>&1 &
}
start_loop heartbeat \
  'while true; do date +%s > "$HOME/.cache/dev-agent/monitors/heartbeat.log"; sleep 60; done'
```

## Team layout that works

Give agents *roles*, not features, and forbid lateral chatter:

```
human → manager → product-owner → implementer lane A / lane B
                     ↑ watchdog files findings as proposals (never builds)
```

- Exactly **one user-facing agent** (the manager): one voice, one place where
  "done" is decided.
- Implementer lanes never talk to each other — everything routes through the
  product-owner. Lateral traffic is how two agents edit the same file.
- Perception agents (watchdog-style) **propose, never execute** — they file
  findings to the coordinator instead of touching repos.

## Liveness: the escalation ladder

1. Registry says the agent is there (`mesh_who`) — proves the *daemon*.
2. Nonce ping the model (`mesh_ping`, agent must echo the nonce) — proves the
   *brain*.
3. No dispatch reply within timeout → re-ping with exponential backoff → then
   escalate to the manager agent.
4. The manager's playbook starts with `tmux capture-pane -t <agent>` — the
   pane is the ground truth (stuck prompt line? login screen? rate-limit
   frame?) — and *fixes* (nudge Enter, respawn a daemon, fresh-restart via the
   launcher), never merely reports.

## Context hygiene

Long-lived sessions fill their context. Never clear — **compact** with an
explicit focus message ("summarize only open threads, decisions, core facts").
State that must survive compaction lives *outside* the context on purpose:
pending-reply ledgers, task boards, user-visible history files. The session is
a worker; files are the memory.
