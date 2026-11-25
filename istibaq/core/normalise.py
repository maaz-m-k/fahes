"""Normaliser: one canonical form for every address.

Lowercase; strip scheme, ``www`` and trailing slash; split the registered
domain (public suffix) and the private-suffix site (e.g. ``shop.github.io``);
decode punycode for display. Uses the Public Suffix List snapshot bundled with
``tldextract``; it never fetches the list at run time.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import unquote, urlsplit

import tldextract

_PUBLIC = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=(), include_psl_private_domains=False)
_PRIVATE = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=(), include_psl_private_domains=True)

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


@dataclass(frozen=True)
class Address:
    raw: str
    url: str                 # canonical form: host + path/query, no scheme, no www, no trailing slash
    host: str                # lowercase ASCII host, no www, no port
    display_host: str        # host with punycode decoded
    path: str                # path + query (+ fragment), may be ""
    registered_domain: str   # registrable domain under the public (ICANN) suffix, e.g. github.io
    suffix: str              # ICANN public suffix, e.g. "gov.ae"
    site: str                # registrable site under private suffixes, e.g. shop.github.io
    private_suffix: str      # the private suffix when it differs from the public one, else ""
    subdomain: str           # labels left of the registered domain
    label: str               # the registrable label, e.g. "tamm" in tamm.abudhabi
    is_ip: bool
    has_userinfo: bool
    port: str
    userinfo: str = ""       # text before "@" in the authority, lowercase; shown to people as if it were the host

    @property
    def is_private_site(self) -> bool:
        return bool(self.private_suffix)


def _decode(host: str) -> str:
    try:
        return host.encode("ascii").decode("idna") if "xn--" in host else host
    except UnicodeError:
        return host


@lru_cache(maxsize=65536)
def normalise(link: str) -> Address:
    raw = (link or "").strip()
    # Browsers read a backslash as a slash; so must we, or "evil.test\\@adpolice.gov.ae" looks official.
    s = raw.strip("\"'<> \t").replace("\\", "/")
    if not _SCHEME.match(s):
        s = "http://" + s.lstrip("/")
    try:
        parts = urlsplit(s)
        netloc = parts.netloc
    except ValueError:
        parts = None
        netloc = s.split("://", 1)[-1].split("/", 1)[0]
    has_userinfo = "@" in netloc
    userinfo = unquote(netloc.rsplit("@", 1)[0]).lower() if has_userinfo else ""
    hostport = netloc.rsplit("@", 1)[-1]
    port = ""
    if hostport.startswith("["):
        host = hostport[1:].split("]", 1)[0]
    else:
        host, _, port = hostport.partition(":")
    host = unquote(host).strip().rstrip(".").lower()
    # Unicode hosts are encoded to punycode so every check sees one form.
    if any(ord(c) > 127 for c in host):
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            pass
    while host.startswith("www."):
        host = host[4:]
    path = ""
    if parts is not None:
        path = parts.path or ""
        if parts.query:
            path += "?" + parts.query
        if parts.fragment:
            path += "#" + parts.fragment
    path = path.rstrip("/") if "?" not in path and "#" not in path else path
    if path == "/":
        path = ""

    is_ip = False
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        pass

    if is_ip:
        reg = suffix = site = label = host
        sub = private_suffix = ""
    else:
        pub = _PUBLIC(host)
        prv = _PRIVATE(host)
        suffix = pub.suffix
        reg = pub.top_domain_under_public_suffix if hasattr(pub, "top_domain_under_public_suffix") else pub.registered_domain
        reg = reg or host
        site = (prv.top_domain_under_public_suffix if hasattr(prv, "top_domain_under_public_suffix") else prv.registered_domain) or reg
        private_suffix = prv.suffix if prv.suffix != pub.suffix else ""
        sub = pub.subdomain
        label = pub.domain or host
        if not suffix and "." in host:
            # Unlisted suffix (e.g. reserved .test/.example): treat the last label as the suffix.
            labels = host.split(".")
            suffix, label = labels[-1], labels[-2]
            reg = site = ".".join(labels[-2:])
            sub = ".".join(labels[:-2])
            private_suffix = ""

    url = host + (":" + port if port else "") + path
    return Address(
        raw=raw, url=url, host=host, display_host=_decode(host), path=path,
        registered_domain=reg, suffix=suffix, site=site, private_suffix=private_suffix,
        subdomain=sub, label=label, is_ip=is_ip, has_userinfo=has_userinfo, port=port, userinfo=userinfo,
    )
