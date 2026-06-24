import fcntl
import os
import sys
import time
import uuid
from pathlib import Path

from .gate import check as gate_check
from .notify import write_notify
from .pending import append_entry, check_overdue, remove_entry
from .registry import deregister as reg_deregister
from .registry import register as reg_register
from .streams import (
    STREAM_MAXLEN,
    cursor_path,
    group_cursor_path,
    group_stream,
    load_cursor,
    pong_stream,
    private_stream,
    reply_stream,
    save_cursor,
    xread_decode,
)
from .transport import get_redis, validate_name


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

    r = get_redis()
    msg_id = str(uuid.uuid4())
    fields = {
        "from": sender,
        "msg": message,
        "ts": str(time.time()),
        "id": msg_id,
    }

    if expect_reply:
        deadline = time.time() + within
        fields["expect_reply"] = "1"
        fields["deadline"] = str(deadline)
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

    r.xadd(private_stream(target), fields, maxlen=STREAM_MAXLEN, approximate=True)

    if not private:
        group_fields = dict(fields)
        group_fields["to"] = target
        r.xadd(group_stream(), group_fields, maxlen=STREAM_MAXLEN, approximate=True)

    return True


def do_listen(me: str, stealth: bool = False) -> int:
    r = get_redis()
    priv_key = private_stream(me)
    grp_key = group_stream()

    priv_cursor = load_cursor(cursor_path(me))
    grp_cursor = load_cursor(group_cursor_path(me))

    try:
        raw = r.xread(
            {priv_key: priv_cursor, grp_key: grp_cursor},
            block=60000,
            count=50,
        )
    except Exception as e:
        print(f"[listen] xread error: {e}", file=sys.stderr)
        return 1

    decoded = xread_decode(raw) if raw else []

    for stream_str, messages in decoded:
        for msg_id, fields in messages:
            is_private = stream_str == priv_key
            sender = fields.get("from", "?")

            if is_private:
                save_cursor(cursor_path(me), msg_id)
                msg_type = fields.get("msg_type", "")
                if msg_type == "ping":
                    nonce = fields.get("nonce", "")
                    try:
                        r.xadd(
                            pong_stream(nonce),
                            {"from": me, "pong": "1"},
                            maxlen=STREAM_MAXLEN,
                            approximate=True,
                        )
                    except Exception:
                        pass
                    continue
                # Real direct message
                msg = fields.get("msg", "")
                if not stealth:
                    print(f"[DIRECT from {sender}] {msg}")
                write_notify(me, sender, msg)
                return 0  # DIRECT received — caller can act on it
            else:
                # Group stream
                save_cursor(group_cursor_path(me), msg_id)
                if sender == me:
                    continue  # Suppress self-echo
                msg = fields.get("msg", "")
                if not stealth:
                    print(f"[GROUP from {sender}] {msg}")
                # Keep looping — GROUP is awareness only

    # Timeout or only group messages — do housekeeping
    def _repingfn(peer, text):
        do_send(peer, f"[re-ping] {text}", me, private=True)

    def _escalate_fn(entry):
        do_send("watchdog", f"[escalate] no reply from {entry.get('peer')} for: {entry.get('note', '')}", me)

    check_overdue(me, _repingfn, _escalate_fn)
    reg_register(me)

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

    reg_register(me)

    while True:
        try:
            do_listen(me, stealth)
        except Exception as e:
            print(f"[monitor] listen error: {e}", file=sys.stderr)
        reg_register(me)
        time.sleep(0.1)


def do_ping(
    target: str,
    timeout_s: float = 5.0,
    sender: str | None = None,
) -> tuple[bool, int]:
    r = get_redis()
    nonce = uuid.uuid4().hex
    sender = sender or "ping"
    r.xadd(
        private_stream(target),
        {
            "from": sender,
            "msg_type": "ping",
            "nonce": nonce,
            "ts": str(time.time()),
        },
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )
    t0 = time.time()
    pong_key = pong_stream(nonce)
    try:
        raw = r.xread({pong_key: "0"}, block=int(timeout_s * 1000), count=1)
    except Exception:
        return (False, -1)

    if raw:
        ms = int((time.time() - t0) * 1000)
        return (True, ms)
    return (False, -1)


def do_request(
    target: str,
    message: str,
    sender: str,
    timeout_s: float = 180.0,
) -> str | None:
    r = get_redis()
    nonce = uuid.uuid4().hex
    reply_key = reply_stream(nonce)
    r.xadd(
        private_stream(target),
        {
            "from": sender,
            "msg": message,
            "reply_to": reply_key,
            "ts": str(time.time()),
            "id": nonce,
        },
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )
    try:
        raw = r.xread({reply_key: "0"}, block=int(timeout_s * 1000), count=1)
    except Exception:
        return None

    if raw:
        decoded = xread_decode(raw)
        for _stream, messages in decoded:
            for _msg_id, fields in messages:
                if "reply" in fields:
                    return fields["reply"]
    return None


def do_reply(reply_stream_name: str, text: str, sender: str | None = None) -> bool:
    r = get_redis()
    sender = sender or "unknown"
    r.xadd(
        reply_stream_name,
        {
            "from": sender,
            "reply": text,
            "ts": str(time.time()),
        },
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )
    return True


def do_ack(peer: str, text: str, sender: str | None = None) -> bool:
    sender = sender or "unknown"
    # Remove any pending entries for this peer from our ledger
    from .pending import load, save_all
    entries = load(sender)
    filtered = [e for e in entries if e.get("peer") != peer]
    save_all(sender, filtered)
    do_send(peer, f"ACK: {text}", sender, private=True)
    return True
