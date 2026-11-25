"""Follow short links and redirects to where a link really lands (online only, no key).

Each hop is requested WITHOUT letting the HTTP client follow, and the next address is checked by the
same address guard as capture (``istibaq.capture.twoview.check_url``: http/https only, no loopback,
private, link-local, multicast or reserved addresses; ``ISTIBAQ_CAPTURE_LOCAL_ONLY=1`` allows only
127.0.0.1). The body is never read. Run this on the server, never against suspect links on a laptop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin

import httpx

from .base import make_client
from .contract import OnlineFacts

Guard = Callable[[str], "str | None"]


def default_guard(url: str) -> str | None:
    from istibaq.capture.twoview import check_url  # same rules as capture
    return check_url(url)


def _scheme_ok(url: str) -> str | None:
    return None if url.lower().startswith(("http://", "https://")) else f"scheme of {url.split(':', 1)[0]!r} not allowed"


@dataclass
class Chain:
    hops: list[str] = field(default_factory=list)   # first to last, including any refused next hop
    stopped: str | None = None                      # why following stopped early, if it did


class LinkExpander:
    name = "expand"

    def __init__(self, client: httpx.Client | None = None, guard: Guard | None = None, max_hops: int = 10):
        self.client = make_client(client, timeout=10.0)
        self.guard = guard or default_guard
        self.max_hops = max_hops

    def chain(self, link: str) -> Chain:
        url = link if "://" in link else "http://" + link
        out = Chain([url])
        for _ in range(self.max_hops + 1):
            why = _scheme_ok(url) or self.guard(url)
            if why:
                out.stopped = why
                return out
            if len(out.hops) > self.max_hops:
                out.stopped = f"too many redirects (more than {self.max_hops})"
                return out
            try:
                resp = self.client.send(self.client.build_request("GET", url), stream=True, follow_redirects=False)
                resp.close()
            except httpx.HTTPError as e:
                out.stopped = f"no answer ({type(e).__name__})"
                return out
            loc = resp.headers.get("location")
            if not (300 <= resp.status_code < 400 and loc):
                return out
            url = urljoin(url, loc.strip())
            out.hops.append(url)
        out.stopped = f"too many redirects (more than {self.max_hops})"
        return out


def online_facts(link: str, expander: LinkExpander | None = None, rdap=None) -> OnlineFacts:
    """Online facts for one link: the redirect chain, and the RDAP age of the link's own domain when an
    ``RDAP`` adapter is given. Failures leave a field unknown; they are never evidence."""
    from istibaq.core.normalise import normalise
    exp = expander or LinkExpander()
    ch = exp.chain(link)
    facts = OnlineFacts(redirect_chain=ch.hops if len(ch.hops) > 1 else None)
    if rdap is not None:
        try:
            facts.rdap_age_days = rdap.age_days(normalise(link).registered_domain)
        except Exception:  # an RDAP failure is unknown age, not a reason
            facts.rdap_age_days = None
    return facts
