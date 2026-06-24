# agent-mesh

Project-agnostic inter-agent messaging multiplexer via Redis Streams, with an MCP server for Claude Code integration. Any number of agents can send, receive, and ping each other over a shared Redis instance — no direct agent-to-agent connections required.

## One-shot setup on a new machine

Open Claude Code and paste the prompt from **[SETUP_PROMPT.md](SETUP_PROMPT.md)**.
Claude will install agent-mesh, start Redis, configure the MCP server, and patch your `~/.claude/CLAUDE.md` — no manual steps.

## Quick start

```bash
# Start Redis
docker-compose up -d

# Install (editable)
pip install -e .

# Verify
agent-mesh who
```

## CLI usage

```bash
# Send a message (appears on group stream + private stream of target)
agent-mesh send cortex "hello from watchdog" --from watchdog

# Send privately (only private stream of target, no group echo)
agent-mesh send cortex "private note" --from watchdog --private

# Send and track reply expectation in pending ledger
agent-mesh send cortex "please respond" --from watchdog --expect-reply --within 120

# Listen (blocks up to 60s, returns on first DIRECT message)
agent-mesh listen watchdog

# Persistent monitor daemon (singleton via flock)
agent-mesh monitor watchdog

# Ping
agent-mesh ping cortex --from watchdog

# Request/reply roundtrip
agent-mesh request cortex "what time is it?" --from watchdog
# (on cortex side) agent-mesh reply mesh:reply:<nonce> "it is noon" --from cortex

# Registry
agent-mesh register cortex --role "main implementer"
agent-mesh who

# Pending ledger
agent-mesh pending watchdog
```

## MCP server setup

### stdio mode (default — recommended for Claude Code)

Add to your Claude Code MCP config (e.g. `.claude/settings.json`):

```json
{
  "mcpServers": {
    "agent-mesh": {
      "command": "agent-mesh",
      "args": ["serve"],
      "env": {
        "AGENT_MESH_REDIS_URL": "redis://localhost:6379/0"
      }
    }
  }
}
```

### HTTP/SSE mode

```bash
agent-mesh serve --http --port 8765
```

Add to MCP config:

```json
{
  "mcpServers": {
    "agent-mesh": {
      "url": "http://localhost:8765/sse"
    }
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
| `mesh_listen_once` | Wait for one message on a private stream |
| `mesh_request` | Send a request and wait for a reply |
| `mesh_pending` | List pending reply-expected entries |

## Architecture

### Streams layout

```
mesh:group              — broadcast; all agents see all messages
mesh:to_<name>          — private stream per agent
mesh:pong:<nonce>       — ephemeral ping/pong rendezvous
mesh:reply:<nonce>      — ephemeral request/reply rendezvous
mesh:gate:audit         — rate gate audit log
```

All streams are capped at 2000 entries (approximate MAXLEN).

### Registry

Agents self-register via `agent-mesh register <name>` or `mesh_register` MCP tool. Each entry is a Redis key `mesh:registry:<name>` with a 180s TTL — the monitor daemon renews the lease on each listen iteration. `agent-mesh who` scans all registry keys and prints live agents.

### Rate gate

A fixed-window counter (`mesh:gate:rate:<sender>-><target>`) limits sends to `AGENT_MESH_GATE_LIMIT` per 10s window. In observe mode (default) over-limit sends are logged to the audit stream but still delivered. Set `AGENT_MESH_GATE_ENFORCE=1` to hard-deny.

### Notify log + harness monitor integration

Every DIRECT message received by `do_listen` is appended to `~/.cache/agent-mesh/notify-<name>.log`. The Claude Code harness `Monitor` tool can watch this file as a waker — add a persistent Monitor on the notify log in your agent's Session-Init to wake the agent on incoming messages without polling.

### Pending ledger

`--expect-reply` sends append an entry to `~/.cache/agent-mesh/pending-<sender>.jsonl`. The monitor loop calls `check_overdue` on each idle iteration: overdue entries trigger exponential re-pings (30/60/120/240s backoff) and escalation to `watchdog` after 4 tries.

## Config env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MESH_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `AGENT_MESH_PREFIX` | `mesh` | Stream key prefix |
| `AGENT_MESH_GATE_ENFORCE` | `0` | Set to `1` to hard-deny over-rate sends |
| `AGENT_MESH_GATE_LIMIT` | `40` | Max sends per sender→target per 10s window |
