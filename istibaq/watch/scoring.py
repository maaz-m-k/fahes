"""Bridge to the scorer.

Uses ``istibaq.core.scorer.score`` when it is installed (the scorer worker's
module). Until then a small stand-in with the same signature keeps the watch,
capture and feeds testable. The stand-in is deliberately simple and its
``model_version`` starts with ``heuristic-standin-``.
"""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urlsplit

from istibaq.adapters.base import now_iso
from istibaq.adapters.contract import OnlineFacts, Reason, Verdict

ScoreFn = Callable[..., Verdict]

# Minimal stand-in register (official families) and brand words.
_OFFICIAL = ("tamm.abudhabi", "adpolice.gov.ae", "abudhabi.ae", "gov.ae", "emiratesnbd.com", "adcb.com",
             "bankfab.com", "adib.ae", "icp.gov.ae", "u.ae")
_BRANDS = {"tamm": "TAMM", "adpolice": "Abu Dhabi Police", "emiratesnbd": "Emirates NBD", "adcb": "ADCB",
           "bankfab": "FAB", "adib": "ADIB", "icp": "ICP", "etisalat": "e&", "adnoc": "ADNOC", "addc": "ADDC"}
_KEYWORDS = ("pay", "login", "fine", "secure", "verify", "update", "refund", "discount", "help", "support")


def _host(link: str) -> str:
    if "://" not in link:
        link = "http://" + link
    return (urlsplit(link).hostname or "").lower().removeprefix("www.")


def _official(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in _OFFICIAL)


def brand_of(host: str) -> str | None:
    labels = re.split(r"[.\-]", host)
    for word, brand in _BRANDS.items():
        if word in labels or any(lbl.startswith(word) for lbl in labels):
            return brand
    return None


def _standin_score(link: str, mode: str = "judging", online: OnlineFacts | None = None) -> Verdict:
    host, t = _host(link), now_iso()
    if _official(host):
        return Verdict(link, "green", False, 0.0,
                       [Reason("register_official", "موقع رسمي مسجل", "Official site in the Genuine Register",
                               {"host": host}, t, False)], "heuristic-standin-0", t)
    reasons: list[Reason] = []
    score = 0.2
    brand = brand_of(host)
    if brand:
        score += 0.45
        reasons.append(Reason("brand_mismatch", f"يشبه علامة {brand} على نطاق غير مملوك لها",
                              f"Looks like {brand} on a domain it does not own", {"brand": brand, "host": host}, t, False))
    if any(k in host for k in _KEYWORDS):
        score += 0.15
    if online:
        if online.rdap_age_days is not None and online.rdap_age_days <= 30:
            score += 0.2
            reasons.append(Reason("new_domain", "نطاق حديث التسجيل", "Newly registered domain",
                                  {"rdap_age_days": online.rdap_age_days}, t, True))
        if online.two_view_difference:
            score += 0.2
            reasons.append(Reason("two_view_difference", "الصفحة تظهر بشكل مختلف للهاتف والخادم",
                                  "Page differs between phone and server views",
                                  {"difference": online.two_view_difference}, t, True))
        if online.ai_reason:
            reasons.append(online.ai_reason)
    score = min(score, 1.0)
    red = score >= 0.9 and len(reasons) >= 2
    return Verdict(link, "red" if red else "grey", red, round(score, 3), reasons, "heuristic-standin-0", t)


def get_scorer() -> ScoreFn:
    try:
        from istibaq.core.scorer import score  # type: ignore
        return score
    except ImportError:
        return _standin_score


def has_brand_mismatch(verdict: Verdict) -> bool:
    return any(r.code == "brand_mismatch" for r in verdict.reasons)
