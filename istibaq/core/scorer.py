"""The layered link scorer.

Layers, in order: normalise; register (green ends it); popular allow-list;
address model (``istibaq.model.load()``, heuristic fallback); independent
reason families; thresholds.

Thresholds (accuracy spike, global fresh fakes 17-24 Nov 2026):
- judging: ``is_fraud`` = not green and score >= 0.9
- officer: red = not green, score >= 0.9 and at least one other independent reason
- red always needs reasons from two independent families
- everything else that is not green is grey ("not official, not accused")
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

from .contract import OnlineFacts, Reason, Verdict
from .normalise import normalise
from . import allowlist, reasons as R, register

Mode = Literal["judging", "officer"]

log = logging.getLogger(__name__)

# Families that describe hosting or come from an optional helper: never the second reason for red.
NOT_INDEPENDENT = {"address", "ai", "hosting", "wall"}

FRAUD_THRESHOLD = 0.9
GREY_SCORE = 0.5
OWNER_CAP = 0.49
HEURISTIC_VERSION = "heuristic-2026-11-25"
_MAX_HOPS = 10

_model_cache: list = []


def _model():
    if not _model_cache:
        m = None
        try:
            import istibaq.model as model_pkg  # the trained address model package (istibaq/model/)
        except ModuleNotFoundError as e:
            log.warning("address model not available (%s); using the heuristic", e)
        else:
            m = model_pkg.load()
        _model_cache.append(m)
    return _model_cache[0]


def model_version() -> str:
    m = _model()
    return getattr(m, "version", None) or HEURISTIC_VERSION if m else HEURISTIC_VERSION


def clear_cache() -> None:
    _score_offline.cache_clear()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _families(rs: list[Reason]) -> set[str]:
    return {R.FAMILY[r.code] for r in rs if r.code in R.FAMILY}


def _combine(base: float, rs: list[Reason]) -> float:
    keep = 1.0 - base
    seen: set[str] = set()
    for r in rs:
        fam = R.FAMILY.get(r.code)
        if not fam or fam == "address" or fam in seen:
            continue
        seen.add(fam)
        keep *= 1.0 - R.weight(r)
    return round(min(1.0, max(0.0, 1.0 - keep)), 4)


def _decide(link: str, score: float, rs: list[Reason], mode: Mode, version: str, capped: bool = False) -> Verdict:
    fams = _families(rs)
    other = fams - NOT_INDEPENDENT
    high = score >= FRAUD_THRESHOLD and not capped
    red = high and len(fams) >= 2 and len(other) >= 1
    is_fraud = red if mode == "officer" else high
    return Verdict(link=link, verdict="red" if red else "grey", is_fraud=is_fraud, score=score,
                   reasons=rs, model_version=version, scored_at=_now())


def _info(code: str, ar: str, en: str, evidence: dict) -> Reason:
    return Reason(code, ar, en, evidence, _now(), False)


@lru_cache(maxsize=50000)
def _score_offline(link: str, mode: Mode) -> Verdict:
    return _score(link, mode, None)


def _score(link: str, mode: Mode, online: OnlineFacts | None, depth: int = 0) -> Verdict:
    version = model_version()
    a = normalise(link)
    if not a.host:
        return Verdict(link, "grey", False, 0.0,
                       [_info("unparseable", "تعذّر قراءة العنوان", "Address could not be read", {"raw": link})],
                       version, _now())

    # Layer: register. Green ends it.
    hit = register.lookup(link)
    if hit.status == "official":
        return Verdict(link, "green", False, 0.0,
                       [_info("register_official", "موقع رسمي مسجّل في السجل الحقيقي",
                              "Official site in the Genuine Register", {"family": hit.family, **hit.evidence})],
                       version, _now())
    if hit.status == "licensed":
        return Verdict(link, "grey", False, 0.0,
                       [_info("register_licensed", "جهة مرخّصة أو مؤشَّر عليها «ليست احتيالاً»",
                              "Licensed neighbour or marked not a scam", {"family": hit.family, **hit.evidence})],
                       version, _now())

    # Layer: popular allow-list (exact domain only, never shared platforms). Subdomains of a popular owner
    # are handled below by capping the address score (allowlist.popular_owner).
    if allowlist.is_popular(link) and online is None:
        return Verdict(link, "grey", False, 0.0,
                       [_info("popular_site", "موقع شائع عالمياً (ليس رسمياً، وغير متّهم)",
                              "Globally popular site (not official, not accused)",
                              {"host": a.host, "source": allowlist.SOURCE})],
                       version, _now())

    # Reverse-DNS names (in-addr.arpa, ip6.arpa) are network infrastructure, never a web page.
    if a.host.endswith(".arpa"):
        return Verdict(link, "grey", False, 0.0,
                       [_info("infrastructure_name", "اسم بنية شبكية (بحث DNS عكسي)، ليس صفحة ويب",
                              "Network infrastructure name (reverse DNS), not a web page", {"host": a.host})],
                       version, _now())

    # Layer: address model.
    m = _model()
    facts: dict = {}
    if m is not None:
        try:
            base = float(m.predict(link))
        except Exception as e:  # keep scoring the batch; say which version scored it
            log.warning("address model failed on one link (%s); heuristic used", e)
            base, facts = R.heuristic_score(a)
            version = HEURISTIC_VERSION
    else:
        base, facts = R.heuristic_score(a)
    base = min(1.0, max(0.0, base))
    owner = allowlist.popular_owner(link)
    if owner:
        # The popular site's owner controls its own subdomains: the address alone cannot accuse them.
        base = min(base, OWNER_CAP)

    # Layer: reason families.
    rs: list[Reason] = []
    if base >= GREY_SCORE:
        rs.append(Reason("address_pattern", "شكل العنوان يشبه روابط الاحتيال", "Address pattern resembles fraud links",
                         {"model_score": round(base, 4), "model_version": version, **facts}, _now(), False))
    if owner:
        rs.append(_info("popular_owner", "نطاق فرعي لموقع شائع عالمياً يملكه صاحب الموقع",
                        "Subdomain of a globally popular site, controlled by that site's owner",
                        {"owner": owner, "source": allowlist.SOURCE}))
    rs += R.offline_reasons(a)
    capped = False
    if online is not None:
        rs += R.online_reasons(a, online)
        chain = [h for h in (online.redirect_chain or []) if h]
        if chain and depth < 1:
            rs += _judge_chain(a, chain[:_MAX_HOPS], mode)
    shortener = any(r.code == "short_link" for r in rs)
    hops_judged = any(r.code == "cross_domain_redirect" or r.evidence.get("hop") for r in rs)
    if shortener and not hops_judged:
        capped = True  # offline, a short link stays grey: destination unknown
    # A free-host page with only hosting reasons never turns red (red needs a non-hosting family, see
    # NOT_INDEPENDENT); its score is not capped, so the judges' is_fraud still uses the raw score.

    score = _combine(base, rs)
    if capped:
        score = min(score, round(FRAUD_THRESHOLD - 0.01, 4))
    return _decide(link, score, rs, mode, version, capped)


def _judge_chain(a, chain: list[str], mode: Mode) -> list[Reason]:
    """Judge every hop of a redirect chain; return reasons found on the hops."""
    out: list[Reason] = []
    hop_domains = []
    worst = None
    for hop in chain:
        h = normalise(hop)
        if not h.host:
            continue
        hop_domains.append(h.site)
        if h.site == a.site:
            continue
        v = _score(hop, mode, None, depth=1)
        if worst is None or v.score > worst[1].score:
            worst = (hop, v)
    final_green = False
    if chain:
        last = normalise(chain[-1])
        final_green = bool(last.host) and register.lookup(chain[-1]).status == "official"
    crosses = len(set(hop_domains) | {a.site}) > 1
    if crosses and not final_green:
        out.append(Reason("cross_domain_redirect", "الرابط يُحوِّل إلى نطاق آخر",
                          "Link redirects to a different domain",
                          {"chain": chain, "hop": chain[-1], "final_verdict": worst[1].verdict if worst else None},
                          _now(), True))
    if worst is not None and not final_green:
        hop, v = worst
        for r in v.reasons:
            if r.code in R.FAMILY and r.code not in ("short_link",):
                out.append(Reason(r.code, f"{r.ar} (في خطوة التحويل {hop})", f"{r.en} (on redirect hop {hop})",
                                  {**r.evidence, "hop": hop}, r.time, True))
    return out


def score(link: str, mode: Mode = "judging", online: OnlineFacts | None = None) -> Verdict:
    if mode not in ("judging", "officer"):
        raise ValueError(f"unknown mode: {mode}")
    if online is None:
        v = _score_offline(link, mode)
        return Verdict(v.link, v.verdict, v.is_fraud, v.score, list(v.reasons), v.model_version, _now())
    return _score(link, mode, online)


def score_many(links: list[str], mode: Mode = "judging",
               online_by_link: dict[str, OnlineFacts] | None = None) -> list[Verdict]:
    online_by_link = online_by_link or {}
    return [score(l, mode, online_by_link.get(l)) for l in links]
