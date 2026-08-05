import sys
import urllib.request

import click

from . import __version__


@click.group()
@click.version_option(__version__, "--version", "-V")
def cli():
    """agent-mesh — central inter-agent messaging hub (MCP server)."""
    pass


@cli.command("serve")
@click.option("--http", "use_http", is_flag=True, help="Serve via HTTP/SSE instead of stdio")
@click.option("--port", default=8765, show_default=True, help="HTTP port")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="HTTP bind host (loopback by default; Docker overrides to 0.0.0.0)")
def cmd_serve(use_http, port, host):
    """Run the hub. The Docker image runs `serve --http`."""
    from .mcp_server import run_server
    run_server(http=use_http, port=port, host=host)


@cli.command("health")
@click.option("--url", default="http://localhost:8765", show_default=True, help="Hub base URL")
def cmd_health(url):
    """Check a running hub's /health endpoint."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=5) as resp:
            body = resp.read().decode()
        import json as _json
        if _json.loads(body).get("ok") is not True:
            raise ValueError(f"unexpected /health payload: {body[:120]}")
        click.echo(body)
    except Exception as e:
        click.echo(f"agent-mesh: hub not reachable at {url} ({e})", err=True)
        sys.exit(1)


def main():
    cli()
