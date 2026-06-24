# Agent-Mesh Setup Prompt

Paste the block below as your first message to Claude Code on the target machine.
Claude will install agent-mesh, wire up Redis, configure the MCP server, and patch your global CLAUDE.md.

---

## Prompt (copy everything between the lines)

---

Set up the `agent-mesh` inter-agent messaging system on this machine. Work through all steps autonomously, verify each one, and report what you did.

### 1 — Install

```bash
pip install git+https://github.com/NG-Bullseye/agent-mesh.git
```

Verify: `agent-mesh --help` exits 0.

### 2 — Redis

Check whether a Redis is already reachable:
```bash
redis-cli -u "${AGENT_MESH_REDIS_URL:-redis://localhost:6379/0}" ping
```

If that returns `PONG`, skip to step 3.

Otherwise check whether Docker is available (`docker info`). If yes, create `~/agent-mesh-redis/docker-compose.yml`:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
volumes:
  redis_data:
```

Then run `docker compose -f ~/agent-mesh-redis/docker-compose.yml up -d` and wait for `redis-cli ping` to return `PONG`.

If Docker is also unavailable, print: "No Redis found and Docker unavailable — set AGENT_MESH_REDIS_URL before using agent-mesh." and continue to step 3 anyway.

### 3 — MCP server configuration

Add `agent-mesh` to the user-level Claude Code MCP config at `~/.claude/settings.json`. Read the file first (create it as `{}` if missing), then merge in the `agent-mesh` entry under `mcpServers`:

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

If `AGENT_MESH_REDIS_URL` is set in the current environment, use that value instead of the default.

Preserve all existing keys in `settings.json` — only add/replace the `agent-mesh` entry under `mcpServers`.

### 4 — Patch ~/.claude/CLAUDE.md

Read `~/.claude/CLAUDE.md`. If the file does not exist, create it with only the section below. If it exists, check whether a `## Agent Mesh` section is already present — if yes, replace it; if no, append it at the end.

Insert/replace this section verbatim:

```markdown
## Agent Mesh

`agent-mesh` is an inter-agent Redis-Streams multiplexer. The MCP server exposes 7 tools for messaging, discovery, and liveness. Source + full docs: https://github.com/NG-Bullseye/agent-mesh

### MCP tools (available after MCP server starts)

| Tool | What it does |
|------|-------------|
| `mesh_send` | Send a message to an agent (`to`, `message`, `from_agent`, optional `private`) |
| `mesh_ping` | Liveness check — returns ok + latency_ms |
| `mesh_who` | List all live agents (registry) |
| `mesh_register` | Register this instance by name + role |
| `mesh_listen_once` | Poll the private stream once (non-blocking, `timeout_s`) |
| `mesh_request` | Send a request, block for reply (`timeout_s=60`) |
| `mesh_pending` | Show open reply-expected entries for a name |

### Session-Init pattern

At the start of any session that wants to participate in the mesh:

1. Call `mesh_register` with a name and role description.
2. Optionally arm a `Monitor` tool on `~/.cache/agent-mesh/notify-<name>.log` with `persistent=true` — this wakes the session when a DIRECT message arrives.

### CLI quick reference

```bash
agent-mesh send <target> "<msg>" --from <me>
agent-mesh listen <name>           # block until one DIRECT message arrives
agent-mesh monitor <name>          # persistent singleton daemon
agent-mesh ping <target>
agent-mesh request <target> "<msg>" --from <me>
agent-mesh who
```

### Config

| Env var | Default | Purpose |
|---------|---------|---------|
| `AGENT_MESH_REDIS_URL` | `redis://localhost:6379/0` | Redis endpoint |
| `AGENT_MESH_PREFIX` | `mesh` | Stream key prefix |
| `AGENT_MESH_GATE_ENFORCE` | `0` | `1` = hard-deny over-rate sends |
```

### 5 — Smoke test

Run the following and report results:

```bash
# Register this machine as a mesh participant
agent-mesh register "$(hostname)" --role "agent-mesh test node"

# List live agents (should show the just-registered name)
agent-mesh who

# Self-ping via CLI
agent-mesh send "$(hostname)" "smoke-test" --from "$(hostname)"
agent-mesh listen "$(hostname)" --timeout 3 2>/dev/null || true
```

Report:
- `agent-mesh` binary path + version (`agent-mesh --version`)
- Redis connectivity: ok / fallback / not available
- `settings.json` path + whether agent-mesh entry was added fresh or merged
- `~/.claude/CLAUDE.md`: created fresh / section appended / section replaced
- `agent-mesh who` output

---
