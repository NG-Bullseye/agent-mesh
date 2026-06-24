from pathlib import Path


def notify_path(name: str) -> Path:
    return Path.home() / ".cache" / "agent-mesh" / f"notify-{name}.log"


def write_notify(name: str, sender: str, message: str) -> None:
    path = notify_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    msg_flat = message.replace("\n", " ").replace("\r", " ")
    with path.open("a") as f:
        f.write(f"📨 {sender}: {msg_flat}\n")
