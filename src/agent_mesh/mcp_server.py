"""Central agent-mesh hub.

A single self-contained asyncio process. It holds every agent's inbox as an
in-memory queue and pushes messages the instant they arrive — no polling. The
hub is exposed to agents as an MCP server (stdio or HTTP/SSE). Agents never
install anything: they point their MCP client at the hub URL and connect.

Event model (think TCP-ish handshake):
  mesh_register   -> "connect": create/refresh this agent's inbox
  mesh_send       -> drop a message into the target's inbox (delivered instantly
                     if the target is currently in mesh_listen)
  mesh_listen     -> block server-side until one DIRECT message arrives or timeout
  mesh_request    -> send + await a reply Future (resolved by mesh_reply)
  mesh_reply      -> resolve the requester's pending Future
  mesh_ping/who   -> liveness from the registry
"""

import asyncio
import json
import os
import time
import uuid

from mcp.server import Server
from mcp.types import TextContent, Tool

from .validate import validate_name

REGISTRY_TTL = 180          # seconds an agent stays "live" without activity
QUEUE_MAX = 1000            # per-inbox cap; oldest dropped on overflow
GATE_WINDOW = 10
GATE_LIMIT = int(os.environ.get("AGENT_MESH_GATE_LIMIT", "40"))
GATE_ENFORCE = os.environ.get("AGENT_MESH_GATE_ENFORCE", "0") == "1"


class Hub:
    def __init__(self) -> None:
        self.inboxes: dict[str, asyncio.Queue] = {}
        self.registry: dict[str, dict] = {}           # name -> {role, ts}
        self.replies: dict[str, asyncio.Future] = {}  # nonce -> future
        self.pending: dict[str, list] = {}            # from_agent -> [entries]
        self._sends: list[tuple] = []                 # (ts, from, to) for rate gate

    # --- inbox / registry -------------------------------------------------
    def _inbox(self, name: str) -> asyncio.Queue:
        q = self.inboxes.get(name)
        if q is None:
            q = asyncio.Queue(maxsize=QUEUE_MAX)
            self.inboxes[name] = q
        return q

    def register(self, name: str, role: str = "") -> None:
        validate_name(name)
        prev = self.registry.get(name, {})
        self.registry[name] = {"role": role or prev.get("role", ""), "ts": time.time()}
        self._inbox(name)

    def live_agents(self) -> list[dict]:
        now = time.time()
        return [
            {"agent": n, "role": d["role"], "ts": d["ts"]}
            for n, d in self.registry.items()
            if now - d["ts"] < REGISTRY_TTL
        ]

    def is_live(self, name: str) -> bool:
        d = self.registry.get(name)
        return bool(d) and (time.time() - d["ts"] < REGISTRY_TTL)

    # --- rate gate --------------------------------------------------------
    def _gate(self, frm: str, to: str) -> tuple[bool, int]:
        now = time.time()
        self._sends = [(t, f, g) for (t, f, g) in self._sends if now - t < GATE_WINDOW]
        rate = sum(1 for (_, f, g) in self._sends if f == frm and g == to) + 1
        self._sends.append((now, frm, to))
        if GATE_ENFORCE and rate > GATE_LIMIT:
            return False, rate
        return True, rate

    # --- messaging --------------------------------------------------------
    def _put(self, q: asyncio.Queue, item: dict) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                q.get_nowait()  # drop oldest, keep flowing
            except asyncio.QueueEmpty:
                pass
            q.put_nowait(item)

    def send(self, to: str, message: str, frm: str,
             private: bool = False, reply_to: str | None = None) -> tuple[bool, int]:
        validate_name(to)
        validate_name(frm)
        ok, rate = self._gate(frm, to)
        if not ok:
            return False, rate

        direct = {
            "scope": "direct", "from": frm, "msg": message,
            "ts": time.time(), "reply_to": reply_to,
        }
        self._put(self._inbox(to), direct)

        if not private:
            group = {"scope": "group", "from": frm, "to": to,
                     "msg": message, "ts": time.time()}
            for name, q in self.inboxes.items():
                if name != frm and name != to:
                    self._put(q, group)
        return True, rate

    async def listen(self, name: str, timeout_s: float) -> dict | None:
        self.register(name, self.registry.get(name, {}).get("role", ""))  # refresh liveness
        q = self._inbox(name)
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None

    async def request(self, to: str, message: str, frm: str, timeout_s: float) -> str | None:
        nonce = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.replies[nonce] = fut
        self.pending.setdefault(frm, []).append(
            {"nonce": nonce, "to": to, "msg": message[:200], "ts": time.time()}
        )
        ok, _ = self.send(to, message, frm, private=True, reply_to=nonce)
        if not ok:
            self.replies.pop(nonce, None)
            return None
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            return None
        finally:
            self.replies.pop(nonce, None)
            self.pending[frm] = [p for p in self.pending.get(frm, []) if p["nonce"] != nonce]

    def reply(self, nonce: str, text: str, frm: str) -> bool:
        fut = self.replies.get(nonce)
        if fut is not None and not fut.done():
            fut.set_result(text)
            return True
        return False


HUB = Hub()
app = Server("agent-mesh")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="mesh_register", description="Register/connect this agent to the hub",
             inputSchema={"type": "object", "properties": {
                 "name": {"type": "string"}, "role": {"type": "string", "default": ""}},
                 "required": ["name"]}),
        Tool(name="mesh_send", description="Send a message to an agent (delivered instantly if it is listening)",
             inputSchema={"type": "object", "properties": {
                 "to": {"type": "string"}, "message": {"type": "string"},
                 "from_agent": {"type": "string"}, "private": {"type": "boolean", "default": False}},
                 "required": ["to", "message", "from_agent"]}),
        Tool(name="mesh_listen", description="Block until one DIRECT message arrives (event-driven, no polling)",
             inputSchema={"type": "object", "properties": {
                 "name": {"type": "string"}, "timeout_s": {"type": "number", "default": 60.0}},
                 "required": ["name"]}),
        Tool(name="mesh_ping", description="Liveness check for an agent via the registry",
             inputSchema={"type": "object", "properties": {
                 "agent": {"type": "string"}}, "required": ["agent"]}),
        Tool(name="mesh_who", description="List all live agents",
             inputSchema={"type": "object", "properties": {}, "required": []}),
        Tool(name="mesh_request", description="Send a request and block for the reply",
             inputSchema={"type": "object", "properties": {
                 "to": {"type": "string"}, "message": {"type": "string"},
                 "from_agent": {"type": "string"}, "timeout_s": {"type": "number", "default": 60.0}},
                 "required": ["to", "message", "from_agent"]}),
        Tool(name="mesh_reply", description="Reply to a request (resolves the requester's pending call)",
             inputSchema={"type": "object", "properties": {
                 "nonce": {"type": "string"}, "text": {"type": "string"},
                 "from_agent": {"type": "string"}}, "required": ["nonce", "text"]}),
        Tool(name="mesh_pending", description="List this agent's outstanding requests",
             inputSchema={"type": "object", "properties": {
                 "name": {"type": "string"}}, "required": ["name"]}),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    def _json(data) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(data))]

    if name == "mesh_register":
        HUB.register(arguments["name"], arguments.get("role", ""))
        return _json({"ok": True})

    if name == "mesh_send":
        ok, rate = HUB.send(arguments["to"], arguments["message"],
                            arguments["from_agent"], private=arguments.get("private", False))
        return _json({"ok": ok, "rate": rate})

    if name == "mesh_listen":
        item = await HUB.listen(arguments["name"], arguments.get("timeout_s", 60.0))
        return _json({"message": item})

    if name == "mesh_ping":
        t0 = time.time()
        ok = HUB.is_live(arguments["agent"])
        return _json({"ok": ok, "latency_ms": int((time.time() - t0) * 1000)})

    if name == "mesh_who":
        return _json({"agents": HUB.live_agents()})

    if name == "mesh_request":
        reply = await HUB.request(arguments["to"], arguments["message"],
                                  arguments["from_agent"], arguments.get("timeout_s", 60.0))
        return _json({"reply": reply})

    if name == "mesh_reply":
        ok = HUB.reply(arguments["nonce"], arguments["text"], arguments.get("from_agent", "?"))
        return _json({"ok": ok})

    if name == "mesh_pending":
        return _json({"entries": HUB.pending.get(arguments["name"], [])})

    return _json({"error": f"unknown tool: {name}"})


# --- transports -----------------------------------------------------------
def run_server(http: bool = False, port: int = 8765, host: str = "0.0.0.0") -> None:
    if not http:
        from mcp.server.stdio import stdio_server

        async def _run():
            async with stdio_server() as (read, write):
                await app.run(read, write, app.create_initialization_options())

        asyncio.run(_run())
        return

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route
    from mcp.server.sse import SseServerTransport
    import uvicorn

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    async def health(_request):
        return JSONResponse({"ok": True, "agents": len(HUB.live_agents())})

    async def agents(_request):
        return JSONResponse({"agents": HUB.live_agents()})

    starlette_app = Starlette(routes=[
        Route("/health", health),
        Route("/agents", agents),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse.handle_post_message),
    ])
    uvicorn.run(starlette_app, host=host, port=port)
