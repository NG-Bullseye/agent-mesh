# Agent-Mesh Setup Prompt

Paste the block below as your first message to Claude Code on the target machine.
Claude installs agent-mesh, registers the MCP server, and patches your global CLAUDE.md.
There is no service to install or start — state lives in a local SQLite file.

---

## Prompt (copy everything between the lines)

---

Set up the `agent-mesh` inter-agent messaging MCP server on this machine. Work through all steps autonomously, verify each one, and report what you did.

### 1 — Install

```bash
pip install git+https://github.com/NG-Bullseye/agent-mesh.git
```

Verify: `agent-mesh --version` prints a version and exits 0.

There is no broker, database server, or container to set up. agent-mesh stores
its state in a local SQLite file at `~/.cache/agent-mesh/mesh.db`, created on
first use.

### 2 — MCP server configuration

Add `agent-mesh` to the user-level Claude Code MCP config at `~/.claude/settings.json`. Read the file first (create it as `{}` if missing), then merge in the `agent-mesh` entry under `mcpServers`:

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

No env vars are required. If you want a non-default database location, add
`"env": { "AGENT_MESH_DB": "/path/to/mesh.db" }`.

Preserve all existing keys in `settings.json` — only add/replace the `agent-mesh` entry under `mcpServers`.

### 3 — Patch ~/.claude/CLAUDE.md

Read `~/.claude/CLAUDE.md`. If the file does not exist, create it with only the section below. If it exists, check whether a `## Agent Mesh` section is already present — if yes, replace it; if no, append it at the end.

Insert/replace this section verbatim:

```markdown
## Agent Mesh

`agent-mesh` is a zero-dependency inter-agent messaging MCP server backed by a
local SQLite file (no Redis, no Docker, nothing to run). The MCP server exposes
7 tools for messaging, discovery, and liveness. Source + full docs:
https://github.com/NG-Bullseye/agent-mesh

### MCP tools (available after MCP server starts)

| Tool | What it does |
|------|-------------|
| `mesh_send` | Send a message to an agent (`to`, `message`, `from_agent`, optional `private`) |
| `mesh_ping` | Liveness check — returns ok + latency_ms |
| `mesh_who` | List all live agents (registry) |
| `mesh_register` | Register this instance by name + role |
| `mesh_listen_once` | Poll the inbox once (`timeout_s`) |
| `mesh_request` | Send a request, block for reply (`timeout_s=60`) |
| `mesh_pending` | Show open reply-expected entries for a name |

### Session-Init pattern

At the start of any session that wants to participate in the mesh:

1. Call `mesh_register` with a name and role description.
2. Optionally arm a `Monitor` tool on `~/.cache/agent-mesh/notify-<name>.log`
   with `persistent=true` — this wakes the session when a DIRECT message arrives.

### CLI quick reference

```bash
agent-mesh send <target> "<msg>" --from <me>
agent-mesh listen <name> --timeout 60   # block until one DIRECT message arrives
agent-mesh monitor <name>               # persistent singleton daemon
agent-mesh ping <target> --from <me>
agent-mesh request <target> "<msg>" --from <me>
agent-mesh who
```

### Config

| Env var | Default | Purpose |
|---------|---------|---------|
| `AGENT_MESH_DB` | `~/.cache/agent-mesh/mesh.db` | SQLite database path |
| `AGENT_MESH_GATE_ENFORCE` | `0` | `1` = hard-deny over-rate sends |
```

### 4 — Smoke test

Run the following and report results:

```bash
# Register this machine as a mesh participant
agent-mesh register "$(hostname)" --role "agent-mesh test node"

# List live agents (should show the just-registered name)
agent-mesh who

# Self-send + receive
agent-mesh send "$(hostname)" "smoke-test" --from "$(hostname)"
agent-mesh listen "$(hostname)" --timeout 3
```

Report:
- `agent-mesh` binary path + version (`agent-mesh --version`)
- SQLite database path (`~/.cache/agent-mesh/mesh.db` unless overridden)
- `settings.json` path + whether agent-mesh entry was added fresh or merged
- `~/.claude/CLAUDE.md`: created fresh / section appended / section replaced
- `agent-mesh who` output

---
