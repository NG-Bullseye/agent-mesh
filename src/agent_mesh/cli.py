import json
import os
import sys

import click
from redis.exceptions import ConnectionError as RedisConnectionError

from . import __version__
from .core import (
    do_ack,
    do_listen,
    do_monitor,
    do_ping,
    do_reply,
    do_request,
    do_send,
)
from .pending import load as load_pending
from .registry import deregister, register, who


@click.group()
@click.version_option(__version__, "--version", "-V")
def cli():
    """agent-mesh — inter-agent messaging multiplexer via Redis Streams."""
    pass


@cli.command("send")
@click.argument("target")
@click.argument("message")
@click.option("--from", "sender", default="cli", show_default=True, help="Sender name")
@click.option("--private", "-p", is_flag=True, help="Private (skip group stream)")
@click.option("--expect-reply", "-e", is_flag=True, help="Track in pending ledger")
@click.option("--within", default=120, show_default=True, help="Reply deadline in seconds")
def cmd_send(target, message, sender, private, expect_reply, within):
    """Send a message to TARGET."""
    ok = do_send(target, message, sender, private=private, expect_reply=expect_reply, within=within)
    if not ok:
        sys.exit(1)


@cli.command("listen")
@click.argument("name")
@click.option("--stealth", is_flag=True, help="Suppress console output")
@click.option("--timeout", default=60.0, show_default=True, help="Block timeout in seconds")
def cmd_listen(name, stealth, timeout):
    """Listen for one event on NAME's streams."""
    rc = do_listen(name, stealth, timeout_s=timeout)
    sys.exit(rc)


@cli.command("monitor")
@click.argument("name")
@click.option("--stealth", is_flag=True, help="Suppress console output")
def cmd_monitor(name, stealth):
    """Run persistent singleton monitor daemon for NAME."""
    do_monitor(name, stealth)


@cli.command("ping")
@click.argument("target")
@click.option("--from", "sender", default=None, help="Sender name")
@click.option("--timeout", default=5.0, show_default=True, help="Timeout in seconds")
def cmd_ping(target, sender, timeout):
    """Ping TARGET and report latency."""
    ok, ms = do_ping(target, timeout_s=timeout, sender=sender)
    if ok:
        click.echo(f"pong from {target} in {ms}ms")
    else:
        click.echo(f"timeout waiting for pong from {target}")
        sys.exit(1)


@cli.command("request")
@click.argument("target")
@click.argument("message")
@click.option("--from", "sender", required=True, help="Sender name")
@click.option("--timeout", default=180.0, show_default=True, help="Timeout in seconds")
def cmd_request(target, message, sender, timeout):
    """Send a request to TARGET and wait for a reply."""
    reply = do_request(target, message, sender, timeout_s=timeout)
    if reply is not None:
        click.echo(reply)
    else:
        click.echo("timeout: no reply received", err=True)
        sys.exit(1)


@cli.command("reply")
@click.argument("reply_stream")
@click.argument("text")
@click.option("--from", "sender", default=None, help="Sender name")
def cmd_reply(reply_stream, text, sender):
    """Post a reply to REPLY_STREAM."""
    do_reply(reply_stream, text, sender=sender)


@cli.command("ack")
@click.argument("peer")
@click.argument("text")
@click.option("--from", "sender", default=None, help="Sender name")
def cmd_ack(peer, text, sender):
    """Acknowledge a message from PEER."""
    do_ack(peer, text, sender=sender)


@cli.command("pending")
@click.argument("name")
def cmd_pending(name):
    """Show pending reply-expected entries for NAME."""
    entries = load_pending(name)
    if not entries:
        click.echo("(no pending entries)")
        return
    for entry in entries:
        click.echo(json.dumps(entry, indent=2))


@cli.command("register")
@click.argument("name")
@click.option("--role", default="", help="Agent role description")
def cmd_register(name, role):
    """Register NAME in the agent registry."""
    register(name, role=role)
    click.echo(f"registered {name}")


@cli.command("deregister")
@click.argument("name")
def cmd_deregister(name):
    """Remove NAME from the agent registry."""
    deregister(name)
    click.echo(f"deregistered {name}")


@cli.command("who")
@click.option("--all", "show_all", is_flag=True, help="Show all fields")
def cmd_who(show_all):
    """List registered agents."""
    agents = who()
    if not agents:
        click.echo("(no agents registered)")
        return
    for agent in agents:
        name = agent.get("agent", "?")
        role = agent.get("role", "")
        pid = agent.get("pid", "?")
        ts = agent.get("ts", "?")
        click.echo(f"{name}  role={role}  pid={pid}  ts={ts}")


@cli.command("serve")
@click.option("--http", "use_http", is_flag=True, help="Serve via HTTP/SSE instead of stdio")
@click.option("--port", default=8765, show_default=True, help="HTTP port")
@click.option("--host", default="0.0.0.0", show_default=True, help="HTTP host")
def cmd_serve(use_http, port, host):
    """Start the MCP server (stdio by default, --http for SSE)."""
    from .mcp_server import run_server
    run_server(http=use_http, port=port, host=host)


def main():
    """Console-script entry point — wraps the CLI with friendly Redis errors."""
    try:
        cli()
    except RedisConnectionError as e:
        url = os.environ.get("AGENT_MESH_REDIS_URL", "redis://localhost:6379/0")
        click.echo(f"agent-mesh: cannot reach Redis at {url} ({e})", err=True)
        click.echo("Start it with `docker-compose up -d` or set AGENT_MESH_REDIS_URL.", err=True)
        sys.exit(1)
