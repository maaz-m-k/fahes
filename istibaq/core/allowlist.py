"""Popular allow-list: the Tranco top 100k, exact domain (or www) only.

``popular_owner`` is separate and weaker: a subdomain of a popular domain is not accused on its
address alone (the scorer caps the address score below the grey line), because the owner controls
it. Brand, age and known-bad reasons still count. Popularity is never a reason for fraud.

Never applies to shared platforms, tunnels, dynamic DNS or shorteners: anyone
can publish under those, so popularity says nothing about one page.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from importlib import resources

from .normalise import normalise
from .register import platform_kind

SOURCE = "Tranco list top 100k (https://tranco-list.eu), fetched 2026-11-25"


@lru_cache(maxsize=1)
def _popular() -> frozenset[str]:
    raw = resources.files("istibaq.data.snapshots").joinpath("tranco_top100k.txt.gz").read_bytes()
    names = gzip.decompress(raw).decode("ascii", "ignore").split()
    out = set()
    for n in names:
        n = n.strip().lower()
        while n.startswith("www."):
            n = n[4:]
        if n:
            out.add(n)
    return frozenset(out)


def is_popular(address: str) -> bool:
    a = normalise(address)
    if not a.host or a.is_ip:
        return False
    if platform_kind(a.host):
        return False
    return a.host in _popular()


@lru_cache(maxsize=1)
def _abused() -> frozenset[str]:
    """Popular domains whose subdomains phishers used before the training cut (training-side data only)."""
    raw = resources.files("istibaq.data.snapshots").joinpath("abused_hosts.json").read_text(encoding="utf-8")
    return frozenset(json.loads(raw)["domains"])


def popular_owner(address: str) -> str | None:
    """The popular registered domain a subdomain belongs to, when its owner controls every name under it.

    Never for shared platforms or private-suffix sites (anyone can publish there), and never for the
    popular domain itself (that is ``is_popular``).
    """
    a = normalise(address)
    if not a.host or a.is_ip or a.private_suffix or a.host == a.registered_domain:
        return None
    if platform_kind(a.host) or platform_kind(a.registered_domain) or a.registered_domain in _abused():
        return None
    return a.registered_domain if a.registered_domain in _popular() else None
