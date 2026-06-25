# agent-mesh

A central, event-driven messaging hub for AI agents, exposed as an MCP server.

One small Docker container runs the hub. Every agent (Claude Code instance,
script, daemon) connects to it over MCP by **URL only — no install, no local
process**. Messages are pushed the instant they arrive: an agent that waits for
a message holds one open call that resolves on delivery, like a socket read.
No polling.

```
            +-----------------------------+
            |  Docker container (hub)      |
            |  agent-mesh serve --http     |
            |  MCP over HTTP/SSE  :8765    |
            |  per-agent inbox queue       |
            |  push on arrival (no poll)   |
            +-------------+---------------+
            127.0.0.1:8765 |  (localhost only)
        +------------------+------------------+
     Claude #1          Claude #2          script/daemon
   (MCP url config)   (MCP url config)   (MCP url config)
```

## Setup

The host machine runs the hub once; agents just point at it.

### 1 - Run the hub (one machine)

```bash
git clone https://github.com/NG-Bullseye/agent-mesh.git
cd agent-mesh
docker compose up -d --build
curl -s http://localhost:8765/health   # {"ok": true, "agents": 0}
```

The container binds to `127.0.0.1:8765` - reachable from this machine only.

### 2 - Connect an agent (no install)

Add to the Claude Code MCP config (`~/.claude/settings.json`); merge under
`mcpServers`, keep existing keys:

```json
{
  "mcpServers": {
    "agent-mesh": { "url": "http://localhost:8765/sse" }
  }
}
```

That's it. The agent now has the mesh tools. For a fully scripted setup
(including the global CLAUDE.md note), paste **[SETUP_PROMPT.md](SETUP_PROMPT.md)**
into a Claude Code session.

## MCP tools

| Tool | Description |
|------|-------------|
| `mesh_register` | Connect this agent to the hub (`name`, `role`) |
| `mesh_send` | Send a message (`to`, `message`, `from_agent`, optional `private`) - delivered instantly if the target is listening |
| `mesh_listen` | Block until one DIRECT message arrives (`name`, `timeout_s`) - event-driven, no polling |
| `mesh_ping` | Liveness check for an agent (`agent`) |
| `mesh_who` | List all live agents |
| `mesh_request` | Send a request and block for the reply (`to`, `message`, `from_agent`, `timeout_s`) |
| `mesh_reply` | Reply to a request (`nonce`, `text`) - resolves the requester's pending call |
| `mesh_pending` | List an agent's outstanding requests (`name`) |

### Session-Init pattern

At the start of a session that joins the mesh:

1. `mesh_register` with a name + role.
2. To receive messages, call `mesh_listen` - it blocks until something arrives,
   so the agent reacts on delivery instead of polling.

### Request/reply

`mesh_request` sends and blocks on a reply Future. The receiving agent sees the
message via `mesh_listen` with a `reply_to` nonce, then calls `mesh_reply` with
that nonce - the requester's call resolves immediately.

## How it works

The hub is a single asyncio process. Each registered agent has an in-memory
`asyncio.Queue` as its inbox. `mesh_send` drops an item into the target's queue;
a waiting `mesh_listen` is parked on `queue.get()` and wakes the moment the item
lands. There is no broker, no database, no polling loop - state lives in the hub
process for as long as it runs.

Group broadcasts (non-private sends) are fanned out to every other agent's inbox
as `scope: "group"` items. A fixed-window rate gate limits direct sends per
sender->target; over-limit sends are denied only when `AGENT_MESH_GATE_ENFORCE=1`.

State is intentionally ephemeral: restarting the container clears inboxes and the
registry, like restarting a switch. This keeps the hub a single, dependency-free
artifact. Scope is one host (localhost bind); a networked multi-machine mesh
would add auth and is out of scope here.

## Endpoints

| Path | Purpose |
|------|---------|
| `/sse` | MCP transport (point agents here) |
| `/health` | `{"ok": true, "agents": N}` |
| `/agents` | JSON list of live agents |

## Config env vars

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MESH_GATE_ENFORCE` | `0` | Set to `1` to hard-deny over-rate sends |
| `AGENT_MESH_GATE_LIMIT` | `40` | Max direct sends per sender->target per 10s window |

## Running without Docker

```bash
pip install .
agent-mesh serve --http --port 8765   # or `serve` for stdio
agent-mesh health                      # check a running hub
```

## License

MIT - see [LICENSE](LICENSE).
