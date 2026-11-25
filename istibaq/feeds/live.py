"""Live feeds: new certificates and new domains, narrowed to UAE brand look-alikes.

Each count carries its label (``live`` when we read the source ourselves,
``borrowed`` when it is a third party's published list) and its source.
Narrowing uses the scorer's brand-mismatch reason.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from istibaq.adapters.base import now_iso
from istibaq.adapters.ct import CTReader
from istibaq.adapters.nrd import SOURCE as NRD_SOURCE
from istibaq.adapters.nrd import NewDomains
from istibaq.watch.scoring import ScoreFn, get_scorer, has_brand_mismatch

# Words used to pre-filter certificate searches before the scorer judges them.
BRAND_WORDS = ("tamm", "adpolice", "emiratesnbd", "adcb", "bankfab", "adib", "icp", "addc", "adnoc", "etisalat")


@dataclass
class FeedCount:
    feed: str             # "certificates" or "new_domains"
    label: str            # "live" or "borrowed"
    source: str
    total: int | None     # all items seen in the window (None when unknown)
    rate_per_hour: float | None
    lookalikes: list[dict] = field(default_factory=list)  # {name, brand, score, verdict}
    at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _lookalike(name: str, score: ScoreFn) -> dict | None:
    v = score(name, mode="judging", online=None)
    if v.verdict == "green" or not has_brand_mismatch(v):
        return None
    brand = next((r.evidence.get("brand") for r in v.reasons if r.code == "brand_mismatch"), None)
    return {"name": name, "brand": brand, "score": v.score, "verdict": v.verdict}


def certificate_count(ct: CTReader, words=BRAND_WORDS, score: ScoreFn | None = None) -> FeedCount:
    """Rate of new certificates in the named log (two tree-head readings) plus UAE look-alikes."""
    score = score or get_scorer()
    first = ct.tree_head()
    second = ct.tree_head()
    rate = CTReader.rate_per_hour(first, second)
    names: set[str] = set()
    for w in words:
        for e in ct.search(f"%{w}%"):
            names.update(n.removeprefix("*.") for n in e.names)
    hits = [h for n in sorted(names) if (h := _lookalike(n, score))]
    return FeedCount("certificates", "live", f"CT log {ct.log_name} (rate) and crt.sh (names)",
                     second.tree_size - first.tree_size, round(rate, 1), hits, now_iso())


def new_domain_count(nrd: NewDomains, score: ScoreFn | None = None) -> FeedCount:
    score = score or get_scorer()
    day, domains = nrd.fetch()
    hits = [h for d in domains if (h := _lookalike(d, score))]
    return FeedCount("new_domains", "borrowed", f"{NRD_SOURCE} ({day})", len(domains), None, hits, now_iso())
