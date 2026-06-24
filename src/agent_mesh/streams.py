import os
from pathlib import Path

STREAM_PREFIX = os.environ.get("AGENT_MESH_PREFIX", "mesh")
STREAM_MAXLEN = 2000


def group_stream() -> str:
    return f"{STREAM_PREFIX}:group"


def private_stream(name: str) -> str:
    return f"{STREAM_PREFIX}:to_{name}"


def pong_stream(nonce: str) -> str:
    return f"{STREAM_PREFIX}:pong:{nonce}"


def reply_stream(nonce: str) -> str:
    return f"{STREAM_PREFIX}:reply:{nonce}"


def audit_stream() -> str:
    return f"{STREAM_PREFIX}:gate:audit"


def xread_decode(raw) -> list:
    """Decode raw xread result from bytes to strings.

    raw format: [(stream_bytes, [(id_bytes, {field_bytes: value_bytes})])]
    returns:    [(stream_str,   [(id_str,   {field_str:  value_str})])]
    """
    if not raw:
        return []
    result = []
    for stream_bytes, messages in raw:
        stream_str = stream_bytes.decode() if isinstance(stream_bytes, bytes) else stream_bytes
        decoded_msgs = []
        for msg_id, fields in messages:
            id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            fields_str = {
                (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                for k, v in fields.items()
            }
            decoded_msgs.append((id_str, fields_str))
        result.append((stream_str, decoded_msgs))
    return result


def _cache_dir() -> Path:
    return Path.home() / ".cache" / "agent-mesh"


def cursor_path(name: str) -> Path:
    return _cache_dir() / f"{name}.id"


def group_cursor_path(name: str) -> Path:
    return _cache_dir() / f"{name}_group.id"


def load_cursor(path: Path) -> str:
    try:
        return path.read_text().strip() or "0"
    except FileNotFoundError:
        return "0"


def save_cursor(path: Path, cursor_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cursor_id)
