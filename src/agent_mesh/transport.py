import os
import re
import redis

_redis = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        url = os.environ.get("AGENT_MESH_REDIS_URL", "redis://localhost:6379/0")
        _redis = redis.Redis.from_url(url, decode_responses=False)
    return _redis


def validate_name(name: str) -> None:
    if not re.match(r"^[A-Za-z0-9_-]+$", name):
        raise ValueError(
            f"Invalid agent name {name!r}: only [A-Za-z0-9_-] allowed"
        )
