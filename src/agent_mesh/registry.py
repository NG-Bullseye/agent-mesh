import json
import os
import time
from .transport import get_redis
from .streams import STREAM_PREFIX

REGISTRY_TTL = 180


def registry_key(name: str) -> str:
    return f"{STREAM_PREFIX}:registry:{name}"


def register(name: str, role: str = "") -> None:
    r = get_redis()
    payload = json.dumps({
        "agent": name,
        "role": role,
        "pid": os.getpid(),
        "ts": time.time(),
    })
    r.setex(registry_key(name), REGISTRY_TTL, payload)


def deregister(name: str) -> None:
    r = get_redis()
    r.delete(registry_key(name))


def who() -> list[dict]:
    r = get_redis()
    results = []
    pattern = f"{STREAM_PREFIX}:registry:*"
    for key in r.scan_iter(match=pattern):
        raw = r.get(key)
        if raw is None:
            continue
        try:
            entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            results.append(entry)
        except (json.JSONDecodeError, AttributeError):
            continue
    return results
