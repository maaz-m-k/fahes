"""Maps listings: judged by name, phone number and website, not only the website.

A listing whose name claims an official body (police, a ministry, TAMM, a bank's customer care, a
helpline) is checked against that body's official numbers and domains in the Genuine Register.
A phone number or website that is not that body's own is a reason. A listing that names no
official body is judged by its website alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import reasons as R
from . import scorer
from .contract import Reason, Verdict
from .normalise import normalise
from .register import Family, data, families

# A family's whole-word names are matched in the listing name; short brand words only as whole words.
_WORD = re.compile(r"[a-z0-9؀-ۿ]+")


@dataclass(frozen=True)
class Claim:
    family: Family
    brand: str | None   # the brand word the name used, when it names one brand inside a family (a bank)


def phone_key(phone: str) -> str:
    """One form for a UAE number: digits only, +971/00971 turned into a leading 0, then 0 dropped
    before toll-free 800 and shared-cost 600 numbers ("+971 600 52 2222" -> "600522222")."""
    d = re.sub(r"\D", "", phone or "")
    if d.startswith("00971"):
        d = "0" + d[5:]
    elif d.startswith("971") and len(d) >= 6:
        d = "0" + d[3:]
    if d.startswith(("0800", "0600")):
        d = d[1:]
    return d


def claims(name: str) -> list[Claim]:
    """Official bodies a listing's name claims to be."""
    low = (name or "").lower()
    words = _WORD.findall(low)
    joined = "".join(words)
    out: list[Claim] = []
    for fam in families():
        if not fam.official:
            continue
        hit_brand = None
        named = fam.name_en.lower() in low or (fam.name_ar and fam.name_ar in (name or ""))
        for b in fam.brands:
            if b in words or (len(b) >= 6 and b in joined):
                hit_brand = b
                break
        if named or hit_brand:
            out.append(Claim(fam, hit_brand))
    return out


def official_numbers(claim: Claim) -> list[str]:
    hl = [h for h in data().get("helplines", []) if h.get("family") == claim.family.family]
    if claim.brand:
        own = [h for h in hl if h.get("brand") in (claim.brand, None)]
        branded = [h for h in hl if h.get("brand") == claim.brand]
        hl = own if branded else [h for h in hl if not h.get("brand")]
    return [h["number"] for h in hl]


def _on_family(link: str, fam: Family) -> bool:
    host = normalise(link).host
    return bool(host) and any(host == d or host.endswith("." + d) for d in fam.domains)


def judge_listing(name: str, phone: str | None = None, website: str | None = None,
                  mode: scorer.Mode = "judging", online=None) -> Verdict:
    """Verdict for one Maps listing. The website, when present, is scored like any link, and the
    listing's own reasons are added to it."""
    base = scorer.score(website, mode=mode, online=online) if website else None
    rs: list[Reason] = list(base.reasons) if base else []
    t = R.now()
    for c in claims(name)[:1]:
        fam = c.family
        nums = official_numbers(c)
        if phone and nums and phone_key(phone) not in {phone_key(n) for n in nums}:
            rs.append(Reason(
                "listing_phone_not_official",
                f"الإدراج على الخريطة يحمل اسم «{fam.name_ar}» لكن رقمه {phone} ليس من أرقامها الرسمية ({'، '.join(nums[:3])})",
                f"Maps listing uses the name of {fam.name_en} but its phone {phone} is not one of its official numbers ({', '.join(nums[:3])})",
                {"listing_name": name, "phone": phone, "claimed": fam.family, "official_numbers": nums}, t, True))
        if website and not _on_family(website, fam):
            rs.append(Reason(
                "listing_site_not_official",
                f"الإدراج على الخريطة يحمل اسم «{fam.name_ar}» لكن موقعه ليس من نطاقاتها الرسمية مثل {fam.domains[0]}",
                f"Maps listing uses the name of {fam.name_en} but its website is not on its official domains such as {fam.domains[0]}",
                {"listing_name": name, "website": website, "claimed": fam.family,
                 "official_domains": list(fam.domains[:4])}, t, True))
    listing_rs = [r for r in rs if r.code.startswith("listing_")]
    link = website or f"maps:{name}"
    version = base.model_version if base else scorer.model_version()
    if not listing_rs:
        if base:
            return base
        return Verdict(link, "grey", False, 0.0, [], version, scorer._now())
    start = base.score if base and base.verdict != "green" else 0.0
    if base and base.verdict == "green":
        rs = [r for r in rs if r.code not in R.INFORMATIONAL] + [r for r in rs if r.code in R.INFORMATIONAL]
    score = scorer._combine(start, rs)
    return scorer._decide(link, score, rs, mode, version)
