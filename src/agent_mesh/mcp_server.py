import asyncio
import json
import time

import mcp.types as types
from mcp.server import Server
from mcp.types import TextContent, Tool

from .core import do_ping, do_reply, do_request, do_send
from .pending import load as load_pending
from .registry import register, who
from .streams import private_stream, xread_decode, STREAM_MAXLEN
from .transport import get_redis

app = Server("agent-mesh")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="mesh_send",
            description="Send a message to an agent via the mesh",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Target agent name"},
                    "message": {"type": "string", "description": "Message text"},
                    "from_agent": {"type": "string", "description": "Sender agent name"},
                    "private": {"type": "boolean", "description": "Skip group stream", "default": False},
                },
                "required": ["to", "message", "from_agent"],
            },
        ),
        Tool(
            name="mesh_ping",
            description="Ping an agent and measure latency",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Target agent name"},
                    "timeout_s": {"type": "number", "description": "Timeout in seconds", "default": 5.0},
                },
                "required": ["agent"],
            },
        ),
        Tool(
            name="mesh_who",
            description="List all registered agents",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="mesh_register",
            description="Register an agent in the registry",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Agent name"},
                    "role": {"type": "string", "description": "Agent role", "default": ""},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="mesh_listen_once",
            description="Wait for one message on an agent's private stream",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Agent name to listen as"},
                    "timeout_s": {"type": "number", "description": "Timeout in seconds", "default": 5.0},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="mesh_request",
            description="Send a request and wait for a reply",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Target agent name"},
                    "message": {"type": "string", "description": "Request text"},
                    "from_agent": {"type": "string", "description": "Sender agent name"},
                    "timeout_s": {"type": "number", "description": "Timeout in seconds", "default": 60.0},
                },
                "required": ["to", "message", "from_agent"],
            },
        ),
        Tool(
            name="mesh_pending",
            description="List pending reply-expected entries for an agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Agent name"},
                },
                "required": ["name"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    def _json(data) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(data))]

    if name == "mesh_send":
        ok = do_send(
            arguments["to"],
            arguments["message"],
            arguments["from_agent"],
            private=arguments.get("private", False),
        )
        return _json({"ok": ok})

    elif name == "mesh_ping":
        ok, ms = do_ping(
            arguments["agent"],
            timeout_s=arguments.get("timeout_s", 5.0),
        )
        return _json({"ok": ok, "latency_ms": ms})

    elif name == "mesh_who":
        agents = who()
        return _json({"agents": agents})

    elif name == "mesh_register":
        register(arguments["name"], role=arguments.get("role", ""))
        return _json({"ok": True})

    elif name == "mesh_listen_once":
        agent_name = arguments["name"]
        timeout_s = arguments.get("timeout_s", 5.0)
        r = get_redis()
        stream_key = private_stream(agent_name)
        try:
            raw = r.xread(
                {stream_key: "$"},
                block=int(timeout_s * 1000),
                count=1,
            )
        except Exception:
            return _json({"message": None})
        if raw:
            decoded = xread_decode(raw)
            for _stream, messages in decoded:
                for msg_id, fields in messages:
                    return _json({"message": {"id": msg_id, **fields}})
        return _json({"message": None})

    elif name == "mesh_request":
        reply = do_request(
            arguments["to"],
            arguments["message"],
            arguments["from_agent"],
            timeout_s=arguments.get("timeout_s", 60.0),
        )
        return _json({"reply": reply})

    elif name == "mesh_pending":
        entries = load_pending(arguments["name"])
        return _json({"entries": entries})

    else:
        return _json({"error": f"unknown tool: {name}"})


def run_server(http: bool = False, port: int = 8765, host: str = "0.0.0.0") -> None:
    if not http:
        # stdio mode
        import asyncio
        from mcp.server.stdio import stdio_server

        async def _run():
            async with stdio_server() as (read, write):
                await app.run(read, write, app.create_initialization_options())

        asyncio.run(_run())
    else:
        # HTTP/SSE mode
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        import uvicorn

        sse = SseServerTransport("/messages")

        async def handle_sse(request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        starlette_app = Starlette(routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages", app=sse.handle_post_message),
        ])

        uvicorn.run(starlette_app, host=host, port=port)
