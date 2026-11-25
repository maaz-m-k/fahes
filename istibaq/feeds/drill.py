"""Readiness-drill detection: find our own harmless page in the certificate feed.

Given the drill page's domain and the time it was published, look it up in
public certificate logs and report when it was found and through which feed.
The service stores the records; publishing the page is out of scope.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from istibaq.adapters.ct import CTReader


@dataclass
class DrillDetection:
    domain: str
    published_at: str
    found_at: str | None      # time the certificate entered a public log
    feed: str                 # through which feed
    minutes_to_find: float | None
    evidence: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def detect_drill(domain: str, published_at: str, ct: CTReader) -> DrillDetection:
    domain = domain.lower().strip(".")
    feed = f"certificate transparency via crt.sh (log rate from {ct.log_name})"
    entries = [e for e in ct.search(f"%{domain}")
               if any(n.removeprefix("*.") == domain or n.endswith("." + domain) for n in e.names)]
    # only certificates logged at or after publication count as "found by the drill"
    after = [e for e in entries if _dt(e.logged_at) >= _dt(published_at)]
    if not after:
        return DrillDetection(domain, published_at, None, feed, None, {"entries": 0})
    first = after[0]
    mins = round((_dt(first.logged_at) - _dt(published_at)).total_seconds() / 60, 1)
    return DrillDetection(domain, published_at, first.logged_at, feed, mins,
                          {"crtsh_id": first.crtsh_id, "names": first.names, "issuer": first.issuer})
