import os
import time
from .transport import get_redis
from .streams import STREAM_PREFIX, audit_stream, STREAM_MAXLEN

GATE_WINDOW = 10
GATE_LIMIT = int(os.environ.get("AGENT_MESH_GATE_LIMIT", "40"))
GATE_ENFORCE = os.environ.get("AGENT_MESH_GATE_ENFORCE", "0") == "1"


def _rate_key(sender: str, target: str) -> str:
    return f"{STREAM_PREFIX}:gate:rate:{sender}->{target}"


def check(sender: str, target: str, message: str) -> tuple[bool, int]:
    """Check rate gate for a send operation.

    Returns (allowed, rate) where allowed is False only in enforce mode when
    limit exceeded. Fails open on Redis errors.
    """
    r = get_redis()
    key = _rate_key(sender, target)
    rate = 0
    try:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        rate = int(count)
        if ttl == -1:
            # Key exists but has no TTL — set it (race-safe: EXPIRE only if missing)
            r.expire(key, GATE_WINDOW)
        elif count == 1:
            # First increment — ensure TTL is set
            r.expire(key, GATE_WINDOW)
    except Exception:
        # Fail open on Redis error
        return (True, 0)

    over_limit = rate > GATE_LIMIT
    if GATE_ENFORCE and over_limit:
        verdict = "deny"
        allowed = False
    elif over_limit:
        verdict = "observe"
        allowed = True
    else:
        verdict = "allow"
        allowed = True

    try:
        r.xadd(
            audit_stream(),
            {
                "from": sender,
                "to": target,
                "rate": str(rate),
                "window": str(GATE_WINDOW),
                "verdict": verdict,
                "ts": str(time.time()),
                "msg": message[:200],
            },
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
    except Exception:
        pass  # Audit failures are non-fatal

    return (allowed, rate)
