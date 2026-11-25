"""AI second opinion on uncertain links: the rules for what a language model's reading may change.

The checker decides first. A language model reads only links the checker could not settle, and only
through one of these fixed policies (each measured alone on the sealed test, see docs/accuracy.md):

- ``second_opinion``: inside a score band, a confident "fake" raises a grey link to the judges' "yes",
  a confident "real" lowers it to "no". The officer setting never changes: the AI is never an
  independent reason, so it can never make red.
- ``brand_reading``: the model names the brand the address imitates; the Genuine Register decides
  whether the address belongs to that brand. A brand outside the register is ignored.
- ``brand_reading_global``: as above, for a brand outside the register, only when the model names the
  brand's own domain, that domain is a popular site (Tranco), the brand's name is written in the
  address, and the address is not on that domain.
- ``builder_clear``: on a free website builder only, a confident "real" lowers a flagged grey link.

The brand ideas can be limited to the officer setting (``officer_only``) and to links the model also
calls fake with confidence (``require_fake``).

Never: a register-green link, a licensed or popular site, network names, a red verdict. The model
never sees the checker's score. Missing opinion means no change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .contract import Reason, Verdict
from .normalise import normalise
from . import allowlist, reasons as R, register

FRAUD_LINE = 0.9
NOT_SENT = {"register_official", "register_licensed", "popular_site", "infrastructure_name", "unparseable"}
IDEAS = ("second_opinion", "brand_reading", "brand_reading_global", "builder_clear")
_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Opinion:
    verdict: str            # "fake" | "real" | "unsure"
    confidence: float       # 0 to 1, the model's own
    brand: str = ""         # the brand the address imitates or names, as the model read it
    brand_domain: str = ""  # that brand's own domain, as the model knows it (checked, never trusted)
    why_en: str = ""
    why_ar: str = ""
    model: str = ""


@dataclass(frozen=True)
class Policy:
    idea: str = "second_opinion"
    conf: float = 0.8       # minimum model confidence
    lo: float = 0.0         # score band [lo, hi) the policy may touch (second_opinion only)
    hi: float = 1.01
    raise_: bool = True
    clear: bool = True
    officer_only: bool = False   # brand ideas: change only the officer setting (red needs two independent reasons)
    require_fake: bool = False   # brand ideas: count the brand only when the model also says "fake" with conf

    def __post_init__(self):
        if self.idea not in IDEAS:
            raise ValueError(f"unknown idea: {self.idea}")


def eligible(v: Verdict) -> bool:
    """Whether a link may be sent to the model at all."""
    return v.verdict != "green" and not ({r.code for r in v.reasons} & NOT_SENT)


def facts(v: Verdict) -> dict:
    """What the model is told: the address and the checker's facts. Never the score or the verdict."""
    a = normalise(v.link)
    plat = register.platform_suffix(a.host) if a.host else None
    brands = [r.evidence.get("brand_en") for r in v.reasons if r.code == "brand_mismatch"]
    return {
        "address": v.link.strip(),
        "checker_reasons": sorted({r.code for r in v.reasons} - {"address_pattern"}),
        "address_model_suspicious": any(r.code == "address_pattern" for r in v.reasons),
        "free_builder": plat if plat and register.platform_kind(a.host) != "shorteners" else "",
        "new_domain": any(r.code == "new_domain" for r in v.reasons),
        "brand_words": [b for b in brands if b],
    }


def _ai_reason(o: Opinion, direction: str) -> Reason:
    en = f"AI second opinion ({o.model}): {direction}. {o.why_en}".strip()
    ar = f"رأي ثانٍ من الذكاء الاصطناعي: {'مزيّف على الأرجح' if direction == 'likely fake' else 'حقيقي على الأرجح'}. {o.why_ar}".strip()
    return Reason("ai_second_opinion", ar, en, {"model": o.model, "verdict": o.verdict,
                                                "confidence": round(o.confidence, 3)}, R.now(), True)


def _flip(v: Verdict, o: Opinion, to_fraud: bool) -> Verdict:
    s = max(v.score, FRAUD_LINE) if to_fraud else min(v.score, round(FRAUD_LINE - 0.01, 4))
    return replace(v, is_fraud=to_fraud, score=s,
                   reasons=[*v.reasons, _ai_reason(o, "likely fake" if to_fraud else "likely real")])


def _family_for(brand: str) -> register.Family | None:
    b = _WORD.sub("", brand.lower())
    if len(b) < 3:
        return None
    for fam in register.families():
        names = {_WORD.sub("", n.lower()) for n in (fam.family, fam.name_en, *fam.brands)}
        if b in names:
            return fam
    return None


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _add_brand(v: Verdict, mode: str, evidence: dict, en: str, ar: str) -> Verdict:
    from . import scorer
    if any(R.FAMILY.get(r.code) == "brand" for r in v.reasons):
        return v  # the register already found a brand: one brand reason is enough
    r = Reason("ai_brand_mismatch", ar, en, evidence, R.now(), True)
    keep = (1.0 - v.score) * (1.0 - R.WEIGHT["brand"])
    rs = [*v.reasons, r]
    return scorer._decide(v.link, round(min(1.0, 1.0 - keep), 4), rs, mode, v.model_version)


def apply(v: Verdict, o: Opinion | None, policy: Policy, mode: str) -> Verdict:
    """The verdict after the policy reads the model's opinion. Pure; never touches what is not eligible."""
    if o is None or not eligible(v) or v.verdict == "red":
        return v
    a = normalise(v.link)
    if policy.idea == "second_opinion":
        if mode != "judging" or o.confidence < policy.conf or not (policy.lo <= v.score < policy.hi):
            return v
        if o.verdict == "fake" and policy.raise_ and not v.is_fraud:
            return _flip(v, o, True)
        if o.verdict == "real" and policy.clear and v.is_fraud:
            return _flip(v, o, False)
        return v
    if policy.idea == "builder_clear":
        kind = register.platform_kind(a.host)
        if (mode == "judging" and kind and kind != "shorteners" and v.is_fraud and o.verdict == "real"
                and o.confidence >= policy.conf):
            return _flip(v, o, False)
        return v
    if not o.brand.strip() or (policy.officer_only and mode != "officer"):
        return v
    if policy.require_fake and (o.verdict != "fake" or o.confidence < policy.conf):
        return v
    if policy.idea == "brand_reading":
        fam = _family_for(o.brand)
        if fam is None or any(_on(a.host, d) for d in fam.domains):
            return v
        return _add_brand(v, mode, {"brand": o.brand, "family": fam.family, "brand_en": fam.name_en,
                                    "official_domains": list(fam.domains[:4]), "read_by": o.model,
                                    "decided_by": "Genuine Register"},
                          f"AI reading: the address imitates {fam.name_en}; the Genuine Register says it is not on "
                          f"its official domains such as {fam.domains[0]}",
                          f"قراءة الذكاء الاصطناعي: العنوان يقلّد «{fam.name_ar}»، والسجل الحقيقي يؤكد أنه ليس من "
                          f"نطاقاتها الرسمية مثل {fam.domains[0]}")
    # brand_reading_global
    if _family_for(o.brand) is not None:
        return v  # register brands are the register's job (brand_reading)
    dom = normalise(o.brand_domain or "")
    word = _WORD.sub("", dom.label or "")
    if not dom.host or not allowlist.is_popular(dom.registered_domain) or len(word) < 4:
        return v
    if _on(a.host, dom.registered_domain):
        return v
    written = _WORD.sub("", R._deconfuse(a.display_host.lower() + a.path.lower()))
    if word not in written:
        return v
    return _add_brand(v, mode, {"brand": o.brand, "brand_domain": dom.registered_domain, "read_by": o.model,
                                "decided_by": "Tranco popular list and the address text"},
                      f"AI reading: the address uses the name of {o.brand} ({dom.registered_domain}) but is not on "
                      f"that site",
                      f"قراءة الذكاء الاصطناعي: العنوان يستخدم اسم «{o.brand}» ({dom.registered_domain}) لكنه ليس على "
                      f"ذلك الموقع")
