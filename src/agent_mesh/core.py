import fcntl
import os
import sys
import time
import uuid
from pathlib import Path

from . import store
from .gate import check as gate_check
from .notify import write_notify
from .pending import append_entry, check_overdue
from .validate import validate_name

POLL_INTERVAL = 0.2


def do_send(
    target: str,
    message: str,
    sender: str,
    private: bool = False,
    expect_reply: bool = False,
    within: int = 120,
) -> bool:
    validate_name(target)
    validate_name(sender)

    allowed, rate = gate_check(sender, target, message)
    if not allowed:
        print(f"[gate] DENIED {sender}->{target} (rate={rate})", file=sys.stderr)
        return False

    msg_id = str(uuid.uuid4())
    store.add_event("direct", from_agent=sender, to_agent=target, kind="msg", body=message)

    if not private:
        store.add_event("group", from_agent=sender, to_agent=target, kind="msg", body=message)

    if expect_reply:
        deadline = time.time() + within
        append_entry(sender, {
            "id": msg_id,
            "dir": "out",
            "peer": target,
            "msg_id": msg_id,
            "sent_ts": time.time(),
            "deadline_ts": deadline,
            "tries": 0,
            "note": message[:200],
            "escalated": False,
        })

    return True


def do_listen(me: str, stealth: bool = False, timeout_s: float = 60.0) -> int:
    last = store.get_cursor(me, "listen")
    deadline = time.time() + timeout_s

    while True:
        rows = store.fetch_for(me, last)
        for row in rows:
            last = row["id"]
            scope = row["scope"]
            sender = row["from_agent"] or "?"

            if scope == "group":
                if sender == me:
                    continue  # suppress self-echo
                if not stealth:
                    print(f"[GROUP from {sender}] {row['body']}")
                continue  # group is awareness only

            # direct
            if row["kind"] == "ping":
                store.add_event("pong", from_agent=me, nonce=row["nonce"])
                continue

            # real direct message
            store.set_cursor(me, "listen", last)
            msg = row["body"] or ""
            reply_to = row["reply_to"]
            if not stealth:
                tag = f" | reply-to {reply_to}" if reply_to else ""
                print(f"[DIRECT from {sender}{tag}] {msg}")
            write_notify(me, sender, msg)
            return 0

        store.set_cursor(me, "listen", last)

        if time.time() >= deadline:
            break
        time.sleep(POLL_INTERVAL)

    # Timeout — housekeeping
    def _repingfn(peer, text):
        do_send(peer, f"[re-ping] {text}", me, private=True)

    def _escalate_fn(entry):
        do_send("watchdog", f"[escalate] no reply from {entry.get('peer')} for: {entry.get('note', '')}", me)

    check_overdue(me, _repingfn, _escalate_fn)
    store.register(me)
    return 0


def do_monitor(me: str, stealth: bool = False) -> None:
    cache_dir = Path.home() / ".cache" / "agent-mesh"
    cache_dir.mkdir(parents=True, exist_ok=True)

    lock_path = cache_dir / f"monitor-{me}.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"monitor already running for {me}")
        sys.exit(0)

    lock_file.write(str(os.getpid()))
    lock_file.flush()

    store.register(me)

    while True:
        try:
            do_listen(me, stealth)
        except Exception as e:
            print(f"[monitor] listen error: {e}", file=sys.stderr)
        store.register(me)
        time.sleep(0.1)


def do_ping(
    target: str,
    timeout_s: float = 5.0,
    sender: str | None = None,
) -> tuple[bool, int]:
    nonce = uuid.uuid4().hex
    sender = sender or "ping"
    store.add_event("direct", from_agent=sender, to_agent=target, kind="ping", nonce=nonce)

    t0 = time.time()
    deadline = t0 + timeout_s
    while time.time() < deadline:
        if store.fetch_rendezvous("pong", nonce):
            return (True, int((time.time() - t0) * 1000))
        time.sleep(POLL_INTERVAL)
    return (False, -1)


def do_request(
    target: str,
    message: str,
    sender: str,
    timeout_s: float = 180.0,
) -> str | None:
    nonce = uuid.uuid4().hex
    store.add_event(
        "direct", from_agent=sender, to_agent=target, kind="msg",
        nonce=nonce, reply_to=nonce, body=message,
    )

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        row = store.fetch_rendezvous("reply", nonce)
        if row:
            return row["body"]
        time.sleep(POLL_INTERVAL)
    return None


def do_reply(reply_nonce: str, text: str, sender: str | None = None) -> bool:
    sender = sender or "unknown"
    store.add_event("reply", from_agent=sender, nonce=reply_nonce, body=text)
    return True


def do_ack(peer: str, text: str, sender: str | None = None) -> bool:
    sender = sender or "unknown"
    from .pending import load, save_all
    entries = load(sender)
    filtered = [e for e in entries if e.get("peer") != peer]
    save_all(sender, filtered)
    do_send(peer, f"ACK: {text}", sender, private=True)
    return True
