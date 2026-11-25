"""Shared adapter plumbing: keys from the environment, cost sink, HTTP client.

Every external service sits behind an adapter that takes an ``httpx.Client``
(tests pass one built on ``httpx.MockTransport`` that replays a recorded
fake) and a ``cost_sink`` the service supplies to write the cost log.
Keys are read only from environment variables and never logged or returned.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Callable

import httpx

CostSink = Callable[[str, float, dict], None]


def no_cost(service: str, amount: float, detail: dict) -> None:
    """Default sink for free services or when the caller does not track cost."""


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class MissingKey(RuntimeError):
    """Raised when an adapter that needs a key is used without one."""


def env_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingKey(f"{name} is not set")
    return value


def has_key(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def make_client(client: httpx.Client | None, timeout: float = 20.0) -> httpx.Client:
    return client if client is not None else httpx.Client(timeout=timeout, follow_redirects=True)


class AdapterError(RuntimeError):
    """A service answered with an error. The message never contains a key."""


def check(resp: httpx.Response, service: str) -> httpx.Response:
    if resp.status_code >= 400:
        raise AdapterError(f"{service} answered HTTP {resp.status_code}")
    return resp
