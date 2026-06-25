"""Thin wrappers over the store registry, kept as a stable import surface."""

from . import store

register = store.register
deregister = store.deregister


def who() -> list[dict]:
    return store.live_agents()
