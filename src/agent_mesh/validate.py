import re

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(f"Invalid agent name {name!r}: only [A-Za-z0-9_-] allowed")
