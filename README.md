# agent-mesh

**Run a 24/7 multi-agent AI team on a single Claude Code subscription — no API
keys, no per-token bills, no idle burn.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-MCP-purple.svg)](https://modelcontextprotocol.io)
[![Transport](https://img.shields.io/badge/transport-SSE%20%C2%B7%20stdio-blue.svg)](#endpoints)

Everyone builds multi-agent systems against metered APIs, where a fleet of
agents idling in a loop is a cloud bill with a heartbeat. This project comes
from the opposite direction, and it's the part almost nobody exploits:

> **Claude Code runs on a flat subscription.** A persistent CLI session that
> does nothing costs nothing. So don't orchestrate stateless API calls —
> keep *sessions* alive in tmux, connect them through a hub, and wake them
> **event-driven** the moment a message lands. The result is a standing team
> of specialist agents — a manager, a product owner, implementers, a watchdog —
> that sleeps for free and spends attention only when there is work.

Three primitives make that work, and this repo provides or documents all three:

1. **The hub** (this package): a central registry + instant message delivery,
   exposed as an MCP server. Agents connect by URL — no install, no polling.
2. **Persistent sessions**: each agent is a long-lived Claude Code CLI session
   in tmux, resumable across restarts (see the [Playbook](docs/PLAYBOOK.md)).
3. **The wake pattern**: agents don't loop — they arm a file monitor that
   *wakes* their session when a relevant line arrives. Idle = silent = free.

```
            +------------------------------+
            |  Docker container (hub)      |
            |  agent-mesh serve --http     |
            |  MCP over HTTP/SSE  :8765    |
            |  central registry + inboxes  |
            |  push on arrival (no poll)   |
            +-------------+----------------+
            127.0.0.1:8765 |  (localhost only)
        +------------------+------------------+
   tmux: manager       tmux: dev-agent     tmux: watchdog
  (Claude Code CLI)   (Claude Code CLI)   (Claude Code CLI)
   sleeping…           working…            sleeping…
        ▲ woken by a monitor on message arrival — not by a polling loop
```

## Setup

The host machine runs the hub once; agents just point at it.

### 1 — Run the hub (one machine)

```bash
git clone https://github.com/NG-Bullseye/agent-mesh.git
cd agent-mesh
docker compose up -d --build
curl -s http://localhost:8765/health   # {"ok": true, "agents": 0}
```

The container binds to `127.0.0.1:8765` — reachable from this machine only.

### 2 — Connect an agent (no install)

Register the hub with Claude Code (user scope — available in every project):

```bash
claude mcp add --transport sse --scope user agent-mesh http://localhost:8765/sse
```

Or per project via a `.mcp.json` in the repo root:

```json
{
  "mcpServers": {
    "agent-mesh": { "type": "sse", "url": "http://localhost:8765/sse" }
  }
}
```

That's it. The agent now has the mesh tools. For a fully scripted setup
(including the global CLAUDE.md note), paste **[SETUP_PROMPT.md](SETUP_PROMPT.md)**
into a Claude Code session. To build a full standing team — launchers, wake
wiring, liveness — follow **[docs/PLAYBOOK.md](docs/PLAYBOOK.md)**.

## MCP tools

| Tool | Description |
|------|-------------|
| `mesh_register` | Connect this agent to the central registry (`name`, `role`) |
| `mesh_send` | Send a message (`to`, `message`, `from_agent`, optional `private`) — delivered instantly if the target is listening |
| `mesh_listen` | Block until one DIRECT message arrives (`name`, `timeout_s`) — event-driven, no polling |
| `mesh_ping` | Liveness check for an agent (`agent`) |
| `mesh_who` | List all live agents in the registry |
| `mesh_request` | Send a request and block for the reply (`to`, `message`, `from_agent`, `timeout_s`) |
| `mesh_reply` | Reply to a request (`nonce`, `text`) — resolves the requester's pending call |
| `mesh_pending` | List an agent's outstanding requests (`name`) |

### Request/reply

`mesh_request` sends and blocks on a reply Future. The receiving agent sees the
message via `mesh_listen` with a `reply_to` nonce, then calls `mesh_reply` with
that nonce — the requester's call resolves immediately.

## Production patterns

These rules come from a mesh of eight specialist agents running this way in
production; every one of them was paid for by an incident:

- **DIRECT is a task trigger, GROUP is awareness.** Only a message addressed
  *to you* creates an obligation. Broadcasts inform; they never demand a
  reply. Mixing the two buries real work under chatter.
- **Every DIRECT message creates a reply debt.** An agent never ends its turn
  with a received DIRECT unanswered — reply, or ACK with an ETA. Debts live in
  a pending ledger that survives context compaction, not in vibes.
- **Dispatch ≠ send.** A *dispatch* is a delegation handshake: it expects a
  reply within a timeout and escalates to the manager agent (with exponential
  re-ping backoff) if none arrives. Status updates use plain sends —
  dispatching status creates false escalations.
- **A live daemon is not a live brain.** Registry heartbeats prove the
  plumbing. To know the *model* is responsive, ping it with a nonce the LLM
  itself must echo back. The gap between those two is exactly the failure
  mode you will actually have.
- **The truth about a stuck agent is its terminal, not the registry.** When an
  agent goes quiet, capture its tmux pane before believing any status table.
- **Compact, never clear.** Clearing a session kills its armed monitors — the
  agent goes deaf, silently. Long-lived sessions get *compacted* (summarized)
  instead; monitors survive compaction.

## The wake pattern

The piece that makes flat-rate agents viable. Two layers, deliberately split:

| Layer | What it does | Can it wake the session? |
|---|---|---|
| shell loop | filters a stream/log, appends matching lines to a notify file | **no** — it only produces lines |
| session monitor | the agent's own file-watch, armed at session init, on that notify file | **yes** — wakes the session per line |

The shell loop produces, the session monitor consumes and wakes. An idle agent
holds no open LLM call and burns nothing; the first relevant line brings it
back with full context. `mesh_listen` is the same idea over the hub: the
blocked call resolves on delivery — a socket read, not a poll.

## How it works

The hub is a single asyncio process. Each registered agent has an in-memory
`asyncio.Queue` as its inbox. `mesh_send` drops an item into the target's queue;
a waiting `mesh_listen` is parked on `queue.get()` and wakes the moment the item
lands. There is no broker, no database, no polling loop — state lives in the hub
process for as long as it runs.

Group broadcasts (non-private sends) are fanned out to every other agent's inbox
as `scope: "group"` items. A fixed-window rate gate limits direct sends per
sender→target; over-limit sends are denied only when `AGENT_MESH_GATE_ENFORCE=1`.

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
| `AGENT_MESH_GATE_LIMIT` | `40` | Max direct sends per sender→target per 10s window |

## Running without Docker

```bash
pip install .
agent-mesh serve --http --port 8765   # or `serve` for stdio
agent-mesh health                      # check a running hub
```

## License

MIT — see [LICENSE](LICENSE).
