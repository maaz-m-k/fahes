"""Public scam lists: fresh phishing links that are live right now, read each round.

- OpenPhish community feed (https://openphish.com/feed.txt): one URL a line, free, credited.
- PhishTank online-valid list, only when it answers without a key (it often refuses; then OpenPhish alone).

``pick`` prefers links that imitate UAE or Gulf brands and fills up to ``limit`` with other fresh ones.
Nothing here opens a page; the capture does that on the server only, with its own address guard.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("istibaq.phishfeed")

OPENPHISH_URL = "https://openphish.com/feed.txt"
PHISHTANK_URL = "https://data.phishtank.com/data/online-valid.json"
OPENPHISH = "OpenPhish"
PHISHTANK = "PhishTank"
CREDIT = {OPENPHISH: "OpenPhish community feed (openphish.com)", PHISHTANK: "PhishTank (phishtank.org)"}
UA = "Fahes-watch/1.0 (public-safety research; credits the list)"

# Brand words of the Genuine Register's families and other Gulf brands. Short words match a whole token only.
UAE_WORDS = (
    "tamm", "adpolice", "abudhabipolice", "dubaipolice", "moi", "police", "uaepass", "uae-pass", "emiratespost",
    "empost", "etisalat", "eand", "du", "adcb", "bankfab", "fab", "emiratesnbd", "enbd", "adib", "dib", "mashreq",
    "rakbank", "cbd", "salik", "rta", "dewa", "addc", "adnoc", "icp", "gdrfa", "mohre", "abudhabi", "dubai", "uae",
    "emirates", "sharjah", "ajman", "aramex", "careem", "noon", "nol", "darb", "mawaqif", "itc",
    # Gulf
    "stc", "alrajhi", "rajhi", "snb", "alahli", "absher", "qnb", "kfh", "nbk", "zain", "ooredoo", "omantel",
    "batelco", "saudipost", "spl", "qpost", "kuwait", "qatar", "oman", "bahrain", "saudi", "ksa", "riyad",
)
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class FeedLink:
    link: str
    list: str          # OPENPHISH or PHISHTANK
    brand_word: str | None

    @property
    def source(self) -> str:
        return "publiclist/" + self.list.lower()


def brand_word(link: str) -> str | None:
    """The first UAE or Gulf brand word in the host or path, or None."""
    try:
        parts = urlsplit(link if "://" in link else "https://" + link)
    except ValueError:
        return None
    text = ((parts.hostname or "") + " " + parts.path).lower()
    tokens = set(_TOKEN.findall(text))
    for w in UAE_WORDS:
        if (len(w) <= 4 and w in tokens) or (len(w) > 4 and w in text):
            return w
    return None


def _host(link: str) -> str:
    try:
        return (urlsplit(link).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def read_openphish(client: httpx.Client) -> list[str]:
    r = client.get(OPENPHISH_URL)
    r.raise_for_status()
    return [x.strip() for x in r.text.splitlines() if x.strip().startswith(("http://", "https://"))]


def read_phishtank(client: httpx.Client) -> list[str]:
    """Only if PhishTank answers without a key; any refusal or a huge body is skipped quietly."""
    r = client.get(PHISHTANK_URL)
    if r.status_code != 200 or len(r.content) > 60_000_000:
        return []
    try:
        rows = r.json()
    except ValueError:
        return []
    return [str(x.get("url", "")).strip() for x in rows if isinstance(x, dict) and str(x.get("url", "")).startswith("http")]


def pick(lists: dict[str, list[str]], limit: int = 10, seen: set[str] | frozenset[str] = frozenset()) -> list[FeedLink]:
    """Brand look-alikes first (UAE and Gulf), then other fresh links; one link per host; skip what we already have."""
    brand, other, hosts, per_word = [], [], set(), {}
    for name, links in lists.items():
        for link in links:
            h = _host(link)
            if not h or h in hosts or link in seen or h in seen:
                continue
            hosts.add(h)
            w = brand_word(link)
            if w and per_word.get(w, 0) < 2:  # at most two of one brand, so the round shows several
                per_word[w] = per_word.get(w, 0) + 1
                brand.append(FeedLink(link, name, w))
            else:
                other.append(FeedLink(link, name, w))
    return (brand + other)[:limit]


def fetch(client: httpx.Client | None = None, limit: int = 10, seen: set[str] | frozenset[str] = frozenset(),
          phishtank: bool = True) -> tuple[list[FeedLink], dict]:
    """Read the lists and pick links. Returns (links, facts) where facts says what each list gave or why not."""
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA})
    lists: dict[str, list[str]] = {}
    facts: dict = {}
    try:
        for name, read in ((OPENPHISH, read_openphish), (PHISHTANK, read_phishtank if phishtank else None)):
            if read is None:
                continue
            try:
                lists[name] = read(client)
                facts[name] = {"links": len(lists[name])}
            except Exception as exc:  # a list being down is reported, never invented
                log.warning("public list %s failed: %s", name, exc)
                facts[name] = {"error": type(exc).__name__}
    finally:
        if own:
            client.close()
    return pick(lists, limit, seen), facts
