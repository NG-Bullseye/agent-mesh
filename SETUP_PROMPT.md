# Agent-Mesh Setup Prompt

Paste the block below as your first message to Claude Code on the target machine.
Claude starts the hub container (once per host) and connects this Claude instance
to it. Connecting agents install nothing — they only get an MCP URL.

---

## Prompt (copy everything between the lines)

---

Set up the `agent-mesh` hub on this machine and connect this Claude instance to it. Work through all steps autonomously, verify each one, and report what you did.

### 1 — Start the hub (skip if already running)

Check whether the hub already answers:

```bash
curl -s http://localhost:8765/health
```

If that returns `{"ok": true, ...}`, the hub is up — go to step 2.

Otherwise start it via Docker (the hub runs in a container; nothing is installed on the host):

```bash
git clone https://github.com/NG-Bullseye/agent-mesh.git ~/agent-mesh-hub 2>/dev/null || git -C ~/agent-mesh-hub pull
cd ~/agent-mesh-hub
docker compose up -d --build
```

Wait until `curl -s http://localhost:8765/health` returns `{"ok": true, ...}`.
The container binds to `127.0.0.1:8765` (this machine only).

If Docker is unavailable, run the hub directly instead:

```bash
pip install ~/agent-mesh-hub
nohup agent-mesh serve --http --port 8765 >/tmp/agent-mesh.log 2>&1 &
```

### 2 — Connect this Claude instance (no install)

Add `agent-mesh` to the user-level MCP config at `~/.claude/settings.json`. Read the file first (create it as `{}` if missing), then merge in this entry under `mcpServers`, preserving all existing keys:

```json
{
  "mcpServers": {
    "agent-mesh": { "url": "http://localhost:8765/sse" }
  }
}
```

The connecting agent installs nothing — it only points at the hub URL.

### 3 — Patch ~/.claude/CLAUDE.md

Read `~/.claude/CLAUDE.md`. If it does not exist, create it with only the section below. If it exists, replace an existing `## Agent Mesh` section or append this one:

```markdown
## Agent Mesh

`agent-mesh` is a central event-driven messaging hub for agents, reached as an
MCP server at http://localhost:8765/sse. The hub runs in Docker; this instance
connects by URL only. Source: https://github.com/NG-Bullseye/agent-mesh

### MCP tools

| Tool | What it does |
|------|-------------|
| `mesh_register` | Connect this instance to the hub (`name`, `role`) |
| `mesh_send` | Send a message (`to`, `message`, `from_agent`, optional `private`) |
| `mesh_listen` | Block until one DIRECT message arrives (`name`, `timeout_s`) — event-driven |
| `mesh_ping` | Liveness check for an agent |
| `mesh_who` | List all live agents |
| `mesh_request` | Send a request, block for the reply |
| `mesh_reply` | Reply to a request (`nonce`, `text`) |
| `mesh_pending` | List outstanding requests for a name |

### Session-Init pattern

1. Call `mesh_register` with a name and role.
2. To receive, call `mesh_listen` — it blocks until a message arrives (no polling).
```

### 4 — Smoke test

After the MCP server is connected (you may need the MCP tools to appear), verify the hub:

```bash
curl -s http://localhost:8765/health
curl -s http://localhost:8765/agents
```

Then, using the MCP tools: `mesh_register` this instance, `mesh_who`, and report.

Report:
- hub: container running / direct process / already up
- `/health` output
- `settings.json` path + whether the agent-mesh entry was added fresh or merged
- `~/.claude/CLAUDE.md`: created / section appended / section replaced
- `mesh_who` result

---
