# ARCHITECTURE — agent-mesh

## Deep Modules — Hub: register → send → listen/wake

Der Hauptflow ist ein einzelner asyncio-Prozess (Docker, `127.0.0.1:8765`): Agenten registrieren sich, `mesh_send` legt ein Item in die `asyncio.Queue` des Ziels, ein geparktes `mesh_listen` wacht sofort auf. Zustand ist flüchtig (kein Broker, keine DB). Deep Module ist die Klasse `Hub`, Fassade der MCP-Dispatcher. Jede Innenleben-Zelle ist datei:zeile und muss per grep -n treffen.

## Flow

**Sequenz** (`src/agent_mesh/mcp_server.py:189 async def call_tool`)

| # | Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|---|
| 1 | Register | name, role | Registry-Eintrag | Name valide | `REGISTRY_TTL` (180 s) | `src/agent_mesh/mcp_server.py:52 def register` |
| 2 | Rate-Gate | sender→target | erlaubt/verweigert | Enforce nur mit Env | `AGENT_MESH_GATE_LIMIT`, `AGENT_MESH_GATE_ENFORCE` | `src/agent_mesh/mcp_server.py:71 def _gate` |
| 3 | Send | to, message | Item in Inbox; group = Fan-out | Inbox-Cap | `QUEUE_MAX` (1000) | `src/agent_mesh/mcp_server.py:91 def send` |
| 4 | Listen | name, timeout | ein DIRECT-Item | blockiert bis Ankunft | `timeout_s` | `src/agent_mesh/mcp_server.py:113 async def listen` |

**Parallel**

| Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|
| Request/Reply | to, message | Antwort über Future | Timeout | `timeout_s` | `src/agent_mesh/mcp_server.py:121 async def request` |
| Namensprüfung | Name | ok/ValueError | `^[A-Za-z0-9_-]+$` | — | `src/agent_mesh/validate.py:6 def validate_name` |
| HTTP | `/sse`, `/health`, `/agents` | MCP-Transport, JSON | `serve --http` | Port 8765 | `src/agent_mesh/mcp_server.py:230 def run_server` |
| CLI | `agent-mesh serve|health` | Server / Health-Check | — | — | `src/agent_mesh/cli.py:43 def main` |

## Schnittstellen

- MCP über SSE `http://localhost:8765/sse` (Routen `src/agent_mesh/mcp_server.py:260 Route("/health"`), Container-Bind nur localhost (`docker-compose.yml`).
- Betriebsmuster für Teams: `docs/PLAYBOOK.md`, Setup-Prompt `SETUP_PROMPT.md`.

## Standard: Deep Modules + Flow

Kanon: `~/repos/speech-engine/ARCHITECTURE.md` § Standard (R1–R5).
