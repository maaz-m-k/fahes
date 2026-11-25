"""Daily newly-registered-domains list (borrowed: WhoisDS free daily file).

WhoisDS publishes yesterday's new registrations as a zip holding
``domain-names.txt``; the download path is base64("YYYY-MM-DD.zip"). The
source URL can be overridden with ``ISTIBAQ_NRD_URL`` (plain text or zip).
"""
from __future__ import annotations

import base64
import io
import os
import zipfile
from datetime import UTC, date, datetime, timedelta

import httpx

from .base import CostSink, check, make_client, no_cost

SOURCE = "WhoisDS free newly-registered-domains list"


def whoisds_url(day: date) -> str:
    token = base64.b64encode(f"{day.isoformat()}.zip".encode()).decode()
    return f"https://www.whoisds.com/whois-database/newly-registered-domains/{token}/nrd"


def parse(content: bytes) -> list[str]:
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            text = "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())
    else:
        text = content.decode("utf-8", "replace")
    out = []
    for line in text.splitlines():
        d = line.strip().lower().split(",")[0]
        if d and not d.startswith("#") and "." in d:
            out.append(d)
    return out


class NewDomains:
    name = "nrd"

    def __init__(self, client: httpx.Client | None = None, cost_sink: CostSink = no_cost):
        self.client = make_client(client, timeout=60.0)
        self.cost_sink = cost_sink

    def fetch(self, day: date | None = None) -> tuple[str, list[str]]:
        """Return (day, domains) for the given day (default: yesterday UTC)."""
        day = day or (datetime.now(UTC).date() - timedelta(days=1))
        url = os.environ.get("ISTIBAQ_NRD_URL") or whoisds_url(day)
        return day.isoformat(), parse(check(self.client.get(url), self.name).content)
