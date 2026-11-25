"""The Genuine Register: the real Abu Dhabi, as data.

``lookup(address)`` says whether an address is ``official``, ``licensed`` or
``unknown``, with the family and evidence. A subdomain of a shared platform
(free host, tunnel, dynamic DNS, shortener) is never official.
``apply_edit`` overlays an officer's mark ("not a scam", "licensed").
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources

from .normalise import normalise

_EDITS: dict[str, dict] = {}


@dataclass
class RegisterHit:
    status: str                 # "official" | "licensed" | "unknown"
    family: str | None = None
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Family:
    family: str
    name_ar: str
    name_en: str
    brands: tuple[str, ...]
    domains: tuple[str, ...]
    source: str
    date: str
    official: bool = True   # False: a global brand whose domains are owned, not accused, never green


def _load_json(package: str, name: str) -> dict:
    return json.loads(resources.files(package).joinpath(name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def data() -> dict:
    return _load_json("istibaq.data.register", "register.json")


@lru_cache(maxsize=1)
def platforms() -> dict:
    return _load_json("istibaq.data.snapshots", "platforms.json")


@lru_cache(maxsize=1)
def families() -> tuple[Family, ...]:
    out = []
    for f in data()["families"]:
        out.append(Family(f["family"], f["name_ar"], f["name_en"], tuple(f.get("brands", [])),
                          tuple(d.lower() for d in f["domains"]), f["source"], f["date"]))
    g = data().get("global_brands", {})
    for f in g.get("brands", []):
        out.append(Family(f["family"], f["name_ar"], f["name_en"], tuple(f.get("brands", [])),
                          tuple(d.lower() for d in f["domains"]), g["source"], g["date"], official=False))
    return tuple(out)


@lru_cache(maxsize=1)
def _domain_index() -> dict[str, Family]:
    return {d: f for f in families() for d in f.domains}


def _under(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def platform_suffix(host: str) -> str | None:
    """The shared-platform domain the host sits on (e.g. s3.amazonaws.com -> amazonaws.com), if any."""
    p = platforms()
    for kind in ("shorteners", "tunnels", "dynamic_dns", "shared_platforms"):
        for d in p[kind]:
            if _under(host, d):
                return d
    return None


def platform_kind(host: str) -> str | None:
    """Return "shared_platforms", "tunnels", "dynamic_dns" or "shorteners" if the host sits on one."""
    p = platforms()
    for kind in ("shorteners", "tunnels", "dynamic_dns", "shared_platforms"):
        for d in p[kind]:
            if _under(host, d):
                return kind
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lookup(address: str) -> RegisterHit:
    a = normalise(address)
    host = a.host
    if not host:
        return RegisterHit("unknown")
    for key in (host, a.site, a.registered_domain):
        edit = _EDITS.get(key)
        if edit and _under(host, key):
            status = "official" if edit["status"] == "official" else "licensed"
            if status == "official" and platform_kind(host):
                status = "licensed"
            return RegisterHit(status, edit.get("family"), {"officer_mark": edit})
    kind = platform_kind(host)
    if kind and kind != "shorteners":
        # Anyone can publish here; the register never vouches for it.
        return RegisterHit("unknown", None, {"platform": kind})
    idx = _domain_index()
    labels = host.split(".")
    for i in range(len(labels) - 1):
        cand = ".".join(labels[i:])
        fam = idx.get(cand)
        if fam and not fam.official:
            return RegisterHit("licensed", fam.family, {
                "matched": cand, "owned_by": fam.name_en, "note": "owned, not accused (global brand, never green)",
                "source": fam.source, "date": fam.date})
        if fam:
            return RegisterHit("official", fam.family, {
                "matched": cand, "name_ar": fam.name_ar, "name_en": fam.name_en,
                "source": fam.source, "date": fam.date})
    for s in data()["official_suffixes"]:
        if host.endswith("." + s["suffix"]):
            return RegisterHit("official", s["family"], {
                "matched": "*." + s["suffix"], "source": s["source"], "date": s["date"]})
    for lic in data().get("licensed", []):
        if _under(host, lic["domain"]):
            return RegisterHit("licensed", lic.get("family"), {
                "matched": lic["domain"], "note": lic.get("note", ""), "source": lic["source"], "date": lic["date"]})
    return RegisterHit("unknown")


def apply_edit(address: str, status: str, source: str, note: str = "") -> RegisterHit:
    """Apply an officer's mark. ``status``: "not_scam", "licensed" or "official".

    Marks live in memory; the service persists them and re-applies them at start.
    """
    status = status.strip().lower().replace("-", "_").replace(" ", "_")
    if status not in ("not_scam", "not_a_scam", "licensed", "official"):
        raise ValueError(f"unknown register status: {status}")
    a = normalise(address)
    if not a.host:
        raise ValueError("empty address")
    key = a.host
    _EDITS[key] = {"status": "not_scam" if status.startswith("not") else status,
                        "source": source, "note": note, "time": _now()}
    from . import scorer  # scores depend on the register
    scorer.clear_cache()
    return lookup(address)


def clear_edits() -> None:
    _EDITS.clear()


def brand_index() -> list[tuple[str, Family]]:
    """(brand word, family) pairs, longest first."""
    pairs = [(b.lower(), f) for f in families() for b in f.brands]
    return sorted(pairs, key=lambda p: -len(p[0]))


_PAYEE_NORM = re.compile(r"[^a-z0-9؀-ۿ]+")


def payee_known(payee: str) -> dict | None:
    p = _PAYEE_NORM.sub("", (payee or "").lower())
    if not p:
        return None
    for entry in data().get("payees", []):
        if _PAYEE_NORM.sub("", entry["name"].lower()) == p:
            return entry
    return None
