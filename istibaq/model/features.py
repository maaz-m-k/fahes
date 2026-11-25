"""Address features for the Istibaq address model.

Everything here works on the bare address only (no network), so dead links are scored too.

Forbidden features (known leak traps): path length, scheme, www, trailing slash and
popularity rank. They are never computed; ``tests/model/test_model.py`` fails if one returns.
Keywords are counted on the host only, so a path never moves the score much.
"""
from __future__ import annotations

import ipaddress
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

import tldextract

FORBIDDEN_FEATURES = ("path_length", "scheme", "www", "trailing_slash", "rank", "popularity")

# Free website builders and hosting platforms: the address alone cannot tell real from fake.
FREE_HOSTS = frozenset("""
000webhostapp.com weebly.com wixsite.com wix.com github.io gitlab.io netlify.app vercel.app
pages.dev workers.dev web.app firebaseapp.com herokuapp.com glitch.me repl.co replit.app
blogspot.com wordpress.com sites.google.com godaddysites.com webflow.io square.site
carrd.co framer.website framer.app myshopify.com azurewebsites.net cloudfront.net
s3.amazonaws.com appspot.com onrender.com fly.dev surge.sh tiiny.site jimdosite.com
yolasite.com webnode.page mystrikingly.com ipfs.io dweb.link r2.dev ngrok.io ngrok-free.app
trycloudflare.com duckdns.org no-ip.org ddns.net hopto.org zapto.org bit.ly
""".split())

SHORTENERS = frozenset("""
bit.ly tinyurl.com t.co goo.gl ow.ly is.gd buff.ly cutt.ly rb.gy t.ly shorturl.at
rebrand.ly s.id tiny.cc bl.ink lnkd.in qrco.de urlz.fr v.gd shorte.st adf.ly
""".split())

KEYWORDS = (
    "login", "signin", "verify", "verification", "secure", "account", "update", "confirm",
    "bank", "pay", "payment", "wallet", "billing", "invoice", "fine", "fines", "refund",
    "support", "service", "auth", "otp", "password", "unlock", "suspend", "customs",
    "delivery", "parcel", "track", "post", "reward", "gift", "claim", "webscr", "portal",
)

# Fallback brand list (brand token -> domains the brand really owns). The scorer's Genuine
# Register is the source of truth; when ``istibaq.core.register`` exists it is consulted too.
BRANDS: dict[str, tuple[str, ...]] = {
    "adpolice": ("adpolice.gov.ae",), "dubaipolice": ("dubaipolice.gov.ae",),
    "tamm": ("tamm.abudhabi",), "abudhabi": ("abudhabi.ae", "tamm.abudhabi"),
    "icp": ("icp.gov.ae",), "mohre": ("mohre.gov.ae",), "dewa": ("dewa.gov.ae",),
    "addc": ("addc.ae",), "aadc": ("aadc.ae",), "rta": ("rta.ae",), "salik": ("salik.ae",),
    "etisalat": ("etisalat.ae", "eand.com"), "adcb": ("adcb.com",), "bankfab": ("bankfab.com",),
    "emiratesnbd": ("emiratesnbd.com",), "adib": ("adib.ae",), "mashreq": ("mashreq.com",),
    "emiratespost": ("emiratespost.ae",), "aramex": ("aramex.com",), "darb": ("darb.ae",),
    "uaepass": ("uaepass.ae",), "mawaqif": ("mawaqif.ae",), "itc": ("itc.gov.ae",),
    "paypal": ("paypal.com",), "apple": ("apple.com", "icloud.com"),
    "microsoft": ("microsoft.com", "live.com", "office.com"), "office365": ("office.com",),
    "outlook": ("outlook.com", "live.com"), "netflix": ("netflix.com",),
    "amazon": ("amazon.com", "amazon.ae"), "facebook": ("facebook.com",),
    "instagram": ("instagram.com",), "whatsapp": ("whatsapp.com",), "google": ("google.com",),
    "dhl": ("dhl.com",), "fedex": ("fedex.com",), "binance": ("binance.com",),
    "coinbase": ("coinbase.com",), "metamask": ("metamask.io",), "chase": ("chase.com",),
}

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)
_PUBLIC = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=False)


@dataclass(frozen=True)
class Parsed:
    host: str          # lowercased host, no www, no port
    rest: str          # path + query, no trailing slash, lowercased
    registered: str    # registered domain under the public suffix list (ICANN part)
    site: str          # registered domain including private suffixes (e.g. foo.github.io)
    suffix: str        # ICANN public suffix
    subdomain: str     # labels left of the registered domain (ICANN view)
    is_private: bool   # host sits under a private suffix (shared platform)


@lru_cache(maxsize=200_000)
def parse(link: str) -> Parsed:
    # Browsers read "\\" as "/": without this, evil.test\\@adpolice.gov.ae parses as adpolice.
    s = link.strip().lower().replace("\\", "/")
    if "://" not in s:
        s = "http://" + s
    try:
        parts = urlsplit(s)
        host = (parts.hostname or "").strip(".")
        rest = parts.path + (("?" + parts.query) if parts.query else "")
    except ValueError:
        host, rest = s.split("://", 1)[1].split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0], ""
    if host.startswith("www."):
        host = host[4:]
    rest = rest.rstrip("/")
    pub = _PUBLIC(host)
    priv = _EXTRACT(host)
    registered = ".".join(p for p in (pub.domain, pub.suffix) if p) or host
    site = ".".join(p for p in (priv.domain, priv.suffix) if p) or host
    return Parsed(host, rest, registered, site, pub.suffix, pub.subdomain, bool(priv.is_private))


def model_text(link: str) -> str:
    """Text the character n-gram model reads: the host only (scheme, www and slash stripped)."""
    return parse(link).host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(re.fullmatch(r"\d+", host))


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def _register_owned(host: str) -> bool | None:
    try:  # the scorer's Genuine Register, when present on main
        from istibaq.core import register  # type: ignore
    except Exception:
        return None
    try:
        return register.lookup(host).status in ("official", "licensed")
    except Exception:
        return None


def brand_on_unowned(p: Parsed) -> str | None:
    """Brand token appearing in the host while the host is not on that brand's own domain."""
    labels = re.split(r"[.\-]", p.host)
    joined = p.host.replace("-", "").replace(".", "")
    for brand, owned in BRANDS.items():
        if (brand in labels or (len(brand) >= 5 and brand in joined)):
            if p.registered in owned or p.site in owned:
                continue
            owned_by_register = _register_owned(p.host)
            if owned_by_register:
                continue
            return brand
    return None


FEATURE_NAMES = (
    "lr_score", "host_length", "max_label_length", "subdomain_count", "hyphens", "digits",
    "is_ip", "is_punycode", "free_host", "shortener", "private_suffix", "brand_unowned",
    "keyword_count", "entropy", "suffix_phish_rate",
)


def facts(link: str, suffix_rate: dict[str, float], default_rate: float) -> list[float]:
    """Address facts in FEATURE_NAMES order, without lr_score (filled by the model)."""
    p = parse(link)
    labels = p.host.split(".") if p.host else [""]
    sub = [x for x in p.subdomain.split(".") if x]
    return [
        float(len(p.host)),
        float(max(len(x) for x in labels)),
        float(len(sub)),
        float(p.host.count("-")),
        float(sum(ch.isdigit() for ch in p.host)),
        float(_is_ip(p.host)),
        float("xn--" in p.host),
        float(p.site in FREE_HOSTS or p.registered in FREE_HOSTS or p.is_private),
        float(p.registered in SHORTENERS or p.host in SHORTENERS),
        float(p.is_private),
        float(brand_on_unowned(p) is not None),
        float(sum(k in p.host for k in KEYWORDS)),
        _entropy(p.host),
        suffix_rate.get(p.suffix, default_rate),
    ]
