"""RDAP domain age (free, no key). Uses the rdap.org bootstrap redirector."""
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from .base import CostSink, check, make_client, no_cost


class RDAP:
    name = "rdap"
    base = "https://rdap.org/domain/"

    def __init__(self, client: httpx.Client | None = None, cost_sink: CostSink = no_cost):
        self.client = make_client(client)
        self.cost_sink = cost_sink

    def registered_at(self, domain: str) -> str | None:
        resp = self.client.get(self.base + domain.lower().strip("."))
        if resp.status_code == 404:
            return None
        check(resp, self.name)
        for ev in resp.json().get("events") or []:
            if ev.get("eventAction") == "registration":
                return ev.get("eventDate")
        return None

    def age_days(self, domain: str, now: datetime | None = None) -> int | None:
        when = self.registered_at(domain)
        if not when:
            return None
        reg = datetime.fromisoformat(when.replace("Z", "+00:00"))
        return max(0, ((now or datetime.now(UTC)) - reg).days)
