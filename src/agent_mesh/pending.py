import json
import time
from pathlib import Path


def _pending_path(name: str) -> Path:
    return Path.home() / ".cache" / "agent-mesh" / f"pending-{name}.jsonl"


def load(name: str) -> list[dict]:
    path = _pending_path(name)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def save_all(name: str, entries: list[dict]) -> None:
    path = _pending_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + ("\n" if entries else ""))


def append_entry(name: str, entry: dict) -> None:
    path = _pending_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def remove_entry(name: str, entry_id: str) -> None:
    entries = load(name)
    filtered = [e for e in entries if e.get("id") != entry_id]
    save_all(name, filtered)


# Backoff tiers in seconds indexed by tries (capped at last)
_BACKOFF = [30, 60, 120, 240]


def check_overdue(name: str, send_fn, escalate_fn) -> None:
    """Re-ping or escalate overdue pending entries.

    send_fn(peer, text) — called to re-ping
    escalate_fn(entry)  — called when tries >= 4 and not yet escalated
    """
    now = time.time()
    entries = load(name)
    changed = False

    for entry in entries:
        deadline = float(entry.get("deadline_ts", 0))
        if deadline >= now:
            continue  # Not yet overdue

        tries = int(entry.get("tries", 0))
        last_ts = float(entry.get("sent_ts", 0))
        backoff = _BACKOFF[min(tries, len(_BACKOFF) - 1)]

        if (now - last_ts) < backoff:
            continue  # Backoff not elapsed

        if tries >= 4 and not entry.get("escalated"):
            try:
                escalate_fn(entry)
            except Exception:
                pass
            entry["escalated"] = True
            changed = True

        try:
            send_fn(entry.get("peer", ""), entry.get("note", "re-ping"))
        except Exception:
            pass

        entry["tries"] = tries + 1
        entry["sent_ts"] = now
        changed = True

    if changed:
        save_all(name, entries)
