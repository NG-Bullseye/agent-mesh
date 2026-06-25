import os

from . import store

GATE_WINDOW = 10
GATE_LIMIT = int(os.environ.get("AGENT_MESH_GATE_LIMIT", "40"))
GATE_ENFORCE = os.environ.get("AGENT_MESH_GATE_ENFORCE", "0") == "1"


def check(sender: str, target: str, message: str) -> tuple[bool, int]:
    """Fixed-window rate gate.

    Returns (allowed, rate). Only denies in enforce mode when over limit.
    Fails open on any store error.
    """
    try:
        rate = store.count_recent(sender, target, GATE_WINDOW) + 1
    except Exception:
        return (True, 0)

    over_limit = rate > GATE_LIMIT
    if GATE_ENFORCE and over_limit:
        verdict, allowed = "deny", False
    elif over_limit:
        verdict, allowed = "observe", True
    else:
        verdict, allowed = "allow", True

    try:
        store.add_event(
            "audit", from_agent=sender, to_agent=target, kind="audit",
            body=f"{verdict} rate={rate}/{GATE_WINDOW}s :: {message[:200]}",
        )
    except Exception:
        pass

    return (allowed, rate)
