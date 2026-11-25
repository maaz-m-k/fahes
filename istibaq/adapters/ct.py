"""Certificate Transparency reader.

Two public, keyless sources:

* the **named log** (RFC 6962 ``get-sth``) gives the tree size; two readings
  give the live rate of new certificates entering that log;
* **crt.sh** (a public CT search over all logs) gives the certificate entries
  for a name pattern, with the time each entry was logged. Used for UAE brand
  words and for finding our readiness-drill page.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import httpx

from .base import CostSink, check, make_client, no_cost

DEFAULT_LOG_NAME = "Google 'Argon2026h2'"
DEFAULT_LOG_URL = "https://ct.googleapis.com/logs/us1/argon2026h2/"


@dataclass
class TreeHead:
    log: str
    tree_size: int
    timestamp: str  # ISO-8601 UTC

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CertEntry:
    names: list[str]
    logged_at: str      # ISO-8601 UTC
    not_before: str
    issuer: str
    crtsh_id: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def _iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(text: str) -> str:
    """crt.sh times are UTC without a zone, sometimes with fractions."""
    dt = datetime.fromisoformat(text.replace("Z", "")).replace(tzinfo=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class CTReader:
    name = "ct"
    crtsh = "https://crt.sh/"

    def __init__(self, client: httpx.Client | None = None, cost_sink: CostSink = no_cost,
                 log_url: str | None = None, log_name: str | None = None):
        self.client = make_client(client, timeout=60.0)
        self.cost_sink = cost_sink
        self.log_url = (log_url or os.environ.get("ISTIBAQ_CT_LOG_URL") or DEFAULT_LOG_URL).rstrip("/") + "/"
        self.log_name = log_name or os.environ.get("ISTIBAQ_CT_LOG_NAME") or DEFAULT_LOG_NAME

    def tree_head(self) -> TreeHead:
        data = check(self.client.get(self.log_url + "ct/v1/get-sth"), self.name).json()
        return TreeHead(self.log_name, int(data["tree_size"]), _iso_from_ms(int(data["timestamp"])))

    @staticmethod
    def rate_per_hour(first: TreeHead, second: TreeHead) -> float:
        t1 = datetime.fromisoformat(first.timestamp.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(second.timestamp.replace("Z", "+00:00"))
        secs = (t2 - t1).total_seconds()
        if secs <= 0:
            return 0.0
        return (second.tree_size - first.tree_size) * 3600.0 / secs

    def search(self, pattern: str, exclude_expired: bool = True) -> list[CertEntry]:
        """Certificates whose names match a crt.sh identity pattern, e.g. ``%.example.com``."""
        params = {"q": pattern, "output": "json"}
        if exclude_expired:
            params["exclude"] = "expired"
        resp = check(self.client.get(self.crtsh, params=params), "crt.sh")
        out: list[CertEntry] = []
        for row in resp.json() or []:
            names = sorted({n.strip().lower() for n in str(row.get("name_value", "")).split("\n") if n.strip()})
            out.append(CertEntry(names, _iso(row["entry_timestamp"]), _iso(row.get("not_before") or row["entry_timestamp"]),
                                 row.get("issuer_name", ""), row.get("id")))
        out.sort(key=lambda e: e.logged_at)
        return out
