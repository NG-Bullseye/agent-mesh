# agent-mesh

A zero-dependency MCP server that lets multiple agents on one machine send, receive, and ping each other. State lives in a single local SQLite file — no Redis, no Docker, no broker, nothing to run. Install it, point your MCP client at it, done.

Any number of agents (Claude Code instances, scripts, daemons) share one `mesh.db` and message each other through it.

## One-shot setup

Open Claude Code and paste the prompt from **[SETUP_PROMPT.md](SETUP_PROMPT.md)**.
Claude installs agent-mesh and registers the MCP server. There is no service to start.

## Quick start

```bash
pip install git+https://github.com/NG-Bullseye/agent-mesh.git
agent-mesh who
```

That's the whole setup. The SQLite file is created on first use at
`~/.cache/agent-mesh/mesh.db` (override with `AGENT_MESH_DB`).

## CLI usage

```bash
# Send a message (lands in target's inbox + the group broadcast)
agent-mesh send cortex "hello from watchdog" --from watchdog

# Send privately (inbox only, no group echo)
agent-mesh send cortex "private note" --from watchdog --private

# Send and track a reply expectation in the pending ledger
agent-mesh send cortex "please respond" --from watchdog --expect-reply --within 120

# Listen (blocks up to --timeout seconds, default 60, returns on first DIRECT message)
agent-mesh listen watchdog --timeout 30

# Persistent monitor daemon (singleton via flock)
agent-mesh monitor watchdog

# Ping
agent-mesh ping cortex --from watchdog

# Request/reply roundtrip
agent-mesh request cortex "what time is it?" --from watchdog
# (on cortex side) agent-mesh reply <nonce> "it is noon" --from cortex
#   the <nonce> is shown in the listener output as "reply-to <nonce>"

# Registry
agent-mesh register cortex --role "main implementer"
agent-mesh who

# Pending ledger
agent-mesh pending watchdog
```

## MCP server setup

### stdio mode (default — recommended for Claude Code)

Add to your Claude Code MCP config (e.g. `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "agent-mesh": {
      "command": "agent-mesh",
      "args": ["serve"]
    }
  }
}
```

No env vars required. Set `AGENT_MESH_DB` if you want a non-default database path.

### HTTP/SSE mode

```bash
pip install "agent-mesh[http]"   # pulls starlette + uvicorn
agent-mesh serve --http --port 8765
```

```json
{
  "mcpServers": {
    "agent-mesh": { "url": "http://localhost:8765/sse" }
  }
}
```

### Available MCP tools

| Tool | Description |
|------|-------------|
| `mesh_send` | Send a message to an agent |
| `mesh_ping` | Ping an agent and measure latency |
| `mesh_who` | List all registered agents |
| `mesh_register` | Register an agent in the registry |
| `mesh_listen_once` | Wait for one message on an inbox |
| `mesh_request` | Send a request and wait for a reply |
| `mesh_pending` | List pending reply-expected entries |

## Architecture

Everything is one SQLite database (WAL mode for concurrent processes). No network services.

### Event model

A single append-only `events` table carries every message. Each row has a `scope`:

```
direct  — addressed to one agent's inbox
group   — broadcast; every agent sees it
pong    — ping/pong rendezvous (matched by nonce)
reply   — request/reply rendezvous (matched by nonce)
audit   — rate-gate decisions
```

A listener reads new rows where `scope='direct' AND to_agent=me`, plus all
`group` rows, ordered by the autoincrement id it last saw (its cursor). The
event table is trimmed to the most recent ~5000 rows on write.

Blocking reads are emulated by short polling (~200 ms), so `ping`/`listen`
latency is on that order rather than the sub-millisecond of a push broker —
the tradeoff for needing no broker at all.

### Registry

`agent-mesh register <name>` upserts a row with a 180s expiry; the monitor
daemon renews it on each idle iteration. `agent-mesh who` lists rows that
haven't expired.

### Rate gate

A fixed-window counter limits direct sends to `AGENT_MESH_GATE_LIMIT` per 10s
window per sender→target. In observe mode (default) over-limit sends are still
delivered but logged to `audit`. Set `AGENT_MESH_GATE_ENFORCE=1` to hard-deny.

### Notify log + harness monitor integration

Every DIRECT message received by `listen` is appended to
`~/.cache/agent-mesh/notify-<name>.log`. The Claude Code `Monitor` tool can
watch that file as a waker, so an agent wakes on incoming messages without
polling from the model side.

### Pending ledger

`--expect-reply` sends append to `~/.cache/agent-mesh/pending-<sender>.jsonl`.
The monitor loop checks overdue entries each idle iteration: overdue ones
trigger exponential re-pings (30/60/120/240s) and escalation to `watchdog`
after 4 tries.

## Config env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MESH_DB` | `~/.cache/agent-mesh/mesh.db` | SQLite database path |
| `AGENT_MESH_GATE_ENFORCE` | `0` | Set to `1` to hard-deny over-rate sends |
| `AGENT_MESH_GATE_LIMIT` | `40` | Max direct sends per sender→target per 10s window |

## License

MIT — see [LICENSE](LICENSE).
