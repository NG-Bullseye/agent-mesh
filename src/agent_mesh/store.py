"""Embedded SQLite-backed message store.

Replaces the former Redis transport. No external service, no extra
dependencies — sqlite3 ships with Python. Multiple agent processes on the
same machine share one database file (WAL mode handles concurrency).
"""

import os
import sqlite3
import threading
import time
from pathlib import Path

# Keep at most this many event rows; older rows are trimmed on write.
EVENT_CAP = 5000
REGISTRY_TTL = 180

_conn = None
_lock = threading.Lock()
_writes = 0


def db_path() -> Path:
    override = os.environ.get("AGENT_MESH_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "agent-mesh" / "mesh.db"


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        _init(conn)
        _conn = conn
    return _conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         REAL    NOT NULL,
            scope      TEXT    NOT NULL,   -- direct | group | pong | reply | audit
            from_agent TEXT,
            to_agent   TEXT,
            kind       TEXT,               -- msg | ping
            nonce      TEXT,
            reply_to   TEXT,
            body       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_to    ON events(to_agent, id);
        CREATE INDEX IF NOT EXISTS idx_events_scope ON events(scope, id);
        CREATE INDEX IF NOT EXISTS idx_events_nonce ON events(nonce);

        CREATE TABLE IF NOT EXISTS registry (
            name    TEXT PRIMARY KEY,
            role    TEXT,
            pid     INTEGER,
            ts      REAL,
            expires REAL
        );

        CREATE TABLE IF NOT EXISTS cursors (
            agent   TEXT,
            scope   TEXT,
            last_id INTEGER,
            PRIMARY KEY (agent, scope)
        );
        """
    )
    conn.commit()


def add_event(
    scope: str,
    from_agent: str,
    to_agent: str | None = None,
    kind: str = "msg",
    nonce: str | None = None,
    reply_to: str | None = None,
    body: str = "",
) -> int:
    conn = get_conn()
    with _lock:
        cur = conn.execute(
            "INSERT INTO events(ts,scope,from_agent,to_agent,kind,nonce,reply_to,body) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), scope, from_agent, to_agent, kind, nonce, reply_to, body),
        )
        conn.commit()
        new_id = cur.lastrowid
        _maybe_trim(conn)
    return new_id


def _maybe_trim(conn: sqlite3.Connection) -> None:
    global _writes
    _writes += 1
    if _writes % 200 != 0:
        return
    conn.execute(
        "DELETE FROM events WHERE id < (SELECT MAX(id) FROM events) - ?",
        (EVENT_CAP,),
    )
    conn.commit()


def fetch_for(me: str, last_id: int, limit: int = 50) -> list[dict]:
    """Direct messages addressed to `me` plus group broadcasts, id-ordered."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM events WHERE id>? AND "
        "((scope='direct' AND to_agent=?) OR scope='group') "
        "ORDER BY id LIMIT ?",
        (last_id, me, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_rendezvous(scope: str, nonce: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM events WHERE scope=? AND nonce=? ORDER BY id LIMIT 1",
        (scope, nonce),
    ).fetchone()
    return dict(row) if row else None


def count_recent(from_agent: str, to_agent: str, window_s: float) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM events "
        "WHERE from_agent=? AND to_agent=? AND scope='direct' AND kind='msg' AND ts > ?",
        (from_agent, to_agent, time.time() - window_s),
    ).fetchone()
    return int(row["n"])


def get_cursor(agent: str, scope: str) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT last_id FROM cursors WHERE agent=? AND scope=?", (agent, scope)
    ).fetchone()
    return int(row["last_id"]) if row else 0


def set_cursor(agent: str, scope: str, last_id: int) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO cursors(agent,scope,last_id) VALUES(?,?,?) "
            "ON CONFLICT(agent,scope) DO UPDATE SET last_id=excluded.last_id",
            (agent, scope, last_id),
        )
        conn.commit()


def register(name: str, role: str = "") -> None:
    conn = get_conn()
    now = time.time()
    with _lock:
        conn.execute(
            "INSERT INTO registry(name,role,pid,ts,expires) VALUES(?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET role=excluded.role, pid=excluded.pid, "
            "ts=excluded.ts, expires=excluded.expires",
            (name, role, os.getpid(), now, now + REGISTRY_TTL),
        )
        conn.commit()


def deregister(name: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM registry WHERE name=?", (name,))
        conn.commit()


def live_agents() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT name,role,pid,ts FROM registry WHERE expires > ? ORDER BY name",
        (time.time(),),
    ).fetchall()
    return [
        {"agent": r["name"], "role": r["role"], "pid": r["pid"], "ts": r["ts"]}
        for r in rows
    ]
