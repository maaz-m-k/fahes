"""Independent reason families.

Each check returns zero or more ``Reason``s. ``FAMILY`` maps every reason code
to its independent family; red needs reasons from two different families.
``WEIGHT`` is how strongly each family raises the score.
Forbidden as evidence anywhere here: path length, scheme, www, trailing slash,
popularity rank.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources

from .contract import OnlineFacts, Reason
from .normalise import Address, normalise
from .register import brand_index, families, payee_known, platform_kind, platform_suffix

FAMILY = {
    "address_pattern": "address",
    "brand_mismatch": "brand",
    "new_domain": "age",
    "free_host": "hosting",
    "short_link": "hosting",
    "ip_host": "hosting",
    "known_bad": "known_bad",
    "young_certificate": "certificate",
    "cross_domain_redirect": "redirect",
    "two_view_difference": "cloaking",
    "live_brand_mismatch": "live_page",
    "human_check_wall": "wall",
    "payee_not_in_register": "payee",
    "ai_page_description": "ai",
    "disguised_address": "disguise",
    "lure_words": "lure",
    "listing_phone_not_official": "listing_phone",
    "listing_site_not_official": "listing_site",
}

WEIGHT = {
    "brand": 0.85, "age": 0.6, "hosting": 0.35, "known_bad": 0.97, "certificate": 0.55,
    "redirect": 0.5, "cloaking": 0.8, "live_page": 0.85, "wall": 0.3, "payee": 0.8, "ai": 0.3,
    "disguise": 0.9, "lure": 0.5, "listing_phone": 0.7, "listing_site": 0.7,
}
WEIGHT_BY_CODE = {"ip_host": 0.6, "short_link": 0.2}

# A brand in the host itself (exact, typo, digit for letter, look-alike letters) is near-certain imitation.
STRONG_BRAND_HOW = {"exact", "typo", "look-alike letters", "official address rewritten", "brand joined to an account word"}
STRONG_BRAND_WEIGHT = 0.92


def weight(r: Reason) -> float:
    fam = FAMILY.get(r.code, "")
    if r.code == "brand_mismatch" and r.evidence.get("where") in ("userinfo", "disguise"):
        return STRONG_BRAND_WEIGHT  # an official name put before "@" only exists to be misread as the host
    if r.code == "brand_mismatch" and r.evidence.get("where") == "host" and r.evidence.get("how") in STRONG_BRAND_HOW:
        return STRONG_BRAND_WEIGHT
    return WEIGHT_BY_CODE.get(r.code, WEIGHT.get(fam, 0.3))

# Families that alone describe how a page is hosted, not that it is fake.
INFORMATIONAL = {"register_official", "register_licensed", "popular_site", "unparseable"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _snap(name: str) -> dict:
    return json.loads(resources.files("istibaq.data.snapshots").joinpath(name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def known_bad() -> tuple[frozenset[str], dict]:
    d = _snap("known_bad.json")
    return frozenset(d["hosts"]), {"source": d["source"], "fetched": d["fetched"]}


class SortedNames:
    """Membership in a sorted, newline-separated name list, by binary search over one bytes blob.

    Holds ~3 million names in about 45 MB without building millions of Python strings.
    """

    def __init__(self, blob: bytes):
        import numpy as np
        blob = blob.replace(b"\r", b"")
        if blob and not blob.endswith(b"\n"):
            blob += b"\n"
        self.blob = blob
        ends = np.flatnonzero(np.frombuffer(blob, dtype=np.uint8) == 10)
        self.starts = np.concatenate(([0], ends[:-1] + 1)) if len(ends) else np.zeros(0, dtype=np.int64)
        self.ends = ends

    def __len__(self) -> int:
        return len(self.ends)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str) or not name:
            return False
        key = name.lower().encode("utf-8", "ignore")
        lo, hi = 0, len(self.ends)
        while lo < hi:
            mid = (lo + hi) // 2
            cur = self.blob[self.starts[mid]:self.ends[mid]]
            if cur < key:
                lo = mid + 1
            elif cur > key:
                hi = mid
            else:
                return True
        return False


@lru_cache(maxsize=1)
def new_domains() -> tuple[SortedNames | frozenset[str], dict]:
    """The bundled newly-registered-domains list (offline domain age), with its source and day."""
    import lzma
    d = _snap("new_domains.json")
    meta = {k: d[k] for k in ("source", "fetched", "list_date") if k in d}
    f = d.get("file")
    if f:
        blob = lzma.decompress(resources.files("istibaq.data.snapshots").joinpath(f).read_bytes())
        return SortedNames(blob), meta
    return frozenset(d["domains"]), meta


# ---------- look-alike letters ----------
_CONFUSABLE = {
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    # Latin extensions
    "ı": "i", "ɡ": "g", "ł": "l", "ø": "o", "ð": "d", "đ": "d", "ħ": "h", "ŧ": "t", "ƚ": "l", "ɩ": "i",
    "ȷ": "j", "ɑ": "a", "ο": "o", "б": "b", "ь": "b", "à": "a", "á": "a", "â": "a", "ä": "a", "å": "a", "ã": "a",
    "è": "e", "é": "e", "ê": "e", "ë": "e", "ì": "i", "í": "i", "î": "i", "ï": "i", "ò": "o", "ó": "o",
    "ô": "o", "ö": "o", "õ": "o", "ù": "u", "ú": "u", "û": "u", "ü": "u", "ç": "c", "ñ": "n", "ý": "y",
    # Arabic and Arabic-Indic digits that pass for Latin letters or digits
    "ا": "l", "١": "l", "٠": "o", "٥": "o", "۵": "o", "۰": "o", "٧": "v", "۷": "v", "٨": "a", "ه": "o",
}
_DIGIT = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "2": "z", "6": "b"})
_DIGIT_I = str.maketrans({"1": "i"})


def _fold(s: str) -> str:
    """Drop Latin diacritics (NFKD, then remove combining marks): tämm -> tamm."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _deconfuse(s: str) -> str:
    return _fold("".join(_CONFUSABLE.get(c, c) for c in s))


# Ordinary words one edit away from a brand; never read as a typo of it.
_TYPO_STOPLIST = frozenset({
    "apply", "apples", "apple", "maple", "ample", "staple", "sample", "dhl", "fedx", "nexflix", "salt", "sales",
    "salic", "mashed", "masher", "mesh", "remix", "netfix", "aramax", "careen", "career", "carees", "careem",
    "paypay", "tamil", "tame", "team", "teams", "tammy", "eland", "grand", "brand", "stand", "island",
    "micro", "microsof", "adorn", "admin", "talabay", "talab", "dewan", "seva", "addon", "adds",
})


def _variants(token: str) -> set[str]:
    t = _deconfuse(token)
    out = {t, t.translate(_DIGIT), t.translate(_DIGIT_I).translate(_DIGIT)}
    out |= {v.replace("rn", "m").replace("vv", "w") for v in list(out)}
    return out


def _edit1(a: str, b: str) -> bool:
    """True when a and b differ by exactly one edit (insert, delete, substitute or swap)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(b)):
        if b[:i] + b[i + 1:] == a:
            return True
    return False


_SPLIT = re.compile(r"[.\-_~/=?&+%]+")


def _host_text(a: Address) -> str:
    return a.display_host


# Account words a bank or service name is glued to in fake addresses ("adcbank", "fabonline").
_JOIN_WORDS = ("bank", "online", "pay", "login", "secure", "verify", "card", "care", "support", "service", "fines")
# Account words in a publisher's own name on a free builder ("login-secure-bank.pages.dev").
LURE_WORDS = frozenset({"login", "logon", "signin", "verify", "verification", "secure", "account", "accounts",
                        "wallet", "bank", "banking", "update", "confirm", "recover", "recovery", "unlock", "suspend",
                        "suspended", "kyc", "otp", "auth", "billing", "payment", "refund", "claim", "reward", "airdrop",
                        "webscr", "password", "validate", "invoice", "fine", "fines", "parcel", "customs"})
_LURE_SPLIT = re.compile(r"[^a-z]+")


def disguise_text(a: Address) -> str:
    """The text a reader is meant to mistake for the host: an official or popular address written before
    "@", or after a backslash and "@" (``evil.test\\@adpolice.gov.ae``). A plain dotted user name is not one."""
    hidden = ""
    if a.userinfo and "." in a.userinfo:
        hidden = a.userinfo.split(":", 1)[0]
    elif "\\@" in a.raw or "\\/@" in a.raw:
        m = re.match(r"/+@([^/?#]+)", a.path)
        hidden = m.group(1).lower() if m else ""
    if not hidden:
        return ""
    from .allowlist import is_popular
    from .register import lookup
    return hidden if lookup(hidden).status != "unknown" or is_popular(hidden) else ""


def _joined(tok: str, brand: str) -> bool:
    for w in _JOIN_WORDS:
        if tok in (brand + w, w + brand) or (brand[-1] == w[0] and tok == brand + w[1:]):
            return True
    return False


def _rewritten(a: Address, fam) -> bool:
    """An official address with its dots turned into hyphens: u-ae.online, adpolice-gov-ae.test."""
    own = a.host[: -len(a.suffix)].rstrip(".") if a.suffix and a.host.endswith(a.suffix) else a.host
    if "-" not in own:
        return False
    flat = own.replace("-", "").replace(".", "")
    return any(d.replace(".", "") == flat for d in fam.domains)


def brand_matches(a: Address) -> list[dict]:
    """Register brands the address imitates while not being on that brand's domains."""
    host = _host_text(a)
    plat = platform_suffix(a.host)
    if plat and a.host != plat:
        # Only the publisher's own labels count: for x.s3.amazonaws.com check "x.s3", never the platform name.
        host = host[: -len(plat)].rstrip(".")
    tokens = [t for t in _SPLIT.split(host) if t]
    joined = "".join(tokens)
    path_tokens = [t for t in _SPLIT.split(a.path.lower()) if t]
    hits: list[dict] = []
    seen: set[str] = set()
    for brand, fam in brand_index():
        if fam.family in seen:
            continue
        if any(a.host == d or a.host.endswith("." + d) for d in fam.domains):
            continue
        how = None
        if fam.official and _rewritten(a, fam):
            how, where = "official address rewritten", "host"
        for tok in ([] if how else tokens):
            vs = _variants(tok)
            if len(brand) >= 3 and _joined(tok, brand):
                how = "brand joined to an account word"
            elif brand in vs:
                how = "exact" if tok == brand else "look-alike letters"
            elif len(brand) >= 5 and any(brand in v and v != brand for v in vs):
                how = "brand plus a word"
            elif len(brand) >= 6 and tok not in _TYPO_STOPLIST and any(
                    v not in _TYPO_STOPLIST and _edit1(v, brand) for v in vs):
                how = "typo"
            if how:
                where = "host"
                break
        if not how and len(brand) >= 6 and any(brand in v for v in _variants(joined)):
            how, where = "brand split across the address", "host"
        hidden = "" if a.userinfo else disguise_text(a)  # text before "@" is handled just below
        if not how and hidden:
            for tok in _SPLIT.split(hidden.replace(":", ".")):
                if tok and brand in _variants(tok):
                    how, where = "brand in a disguised address", "disguise"
                    break
        if not how and a.userinfo:
            for tok in _SPLIT.split(a.userinfo.replace(":", ".")):
                if tok and brand in _variants(tok):
                    how, where = "brand before the @", "userinfo"
                    break
        if not how and len(brand) >= 5:
            for tok in path_tokens:
                if tok == brand or (len(tok) <= len(brand) + 8 and brand in tok):
                    how, where = "brand in the path", "path"
                    break
        if how:
            seen.add(fam.family)
            hits.append({"brand": brand, "family": fam.family, "brand_ar": fam.name_ar, "brand_en": fam.name_en,
                         "how": how, "where": where, "official_domains": list(fam.domains[:4])})
    return hits


# ---------- offline families ----------

_HOW_AR = {"exact": "الاسم نفسه", "look-alike letters": "حروف متشابهة", "brand plus a word": "الاسم مع كلمة إضافية",
           "typo": "خطأ إملائي مقصود", "brand split across the address": "الاسم موزّع على العنوان",
           "brand in the path": "الاسم في مسار الرابط", "brand before the @": "الاسم قبل علامة @",
           "official address rewritten": "العنوان الرسمي مكتوب بشرطات بدل النقاط",
           "brand joined to an account word": "الاسم ملتصق بكلمة حساب أو دفع",
           "brand in a disguised address": "الاسم في عنوان مُموَّه"}


def offline_reasons(a: Address) -> list[Reason]:
    t = now()
    out: list[Reason] = []
    for hit in brand_matches(a)[:2]:
        out.append(Reason(
            "brand_mismatch",
            f"العنوان يقلّد «{hit['brand_ar']}» ({_HOW_AR.get(hit['how'], hit['how'])}) لكنه ليس من نطاقاتها الرسمية مثل {hit['official_domains'][0]}",
            f"Address imitates {hit['brand_en']} ({hit['how']}) but is not on its official domains such as {hit['official_domains'][0]}",
            hit, t, False))
        break  # one brand reason is enough; more brands do not make it more independent
    hidden = disguise_text(a)
    if hidden:
        out.append(Reason("disguised_address",
                          f"العنوان مكتوب ليبدو كأنه «{hidden}» بينما يفتح الموقع {a.host}",
                          f"Address is written to look like \"{hidden}\" but actually opens {a.host}",
                          {"shown": hidden, "real_host": a.host}, t, False))
    nd, nd_meta = new_domains()
    if not a.is_ip and not a.private_suffix and (a.registered_domain in nd or a.host in nd):
        day = nd_meta.get("list_date", nd_meta.get("fetched", ""))[:10]
        out.append(Reason("new_domain", f"النطاق مسجّل حديثاً: ظهر في قائمة النطاقات الجديدة (أسبوع حتى {day})",
                          f"Domain was registered recently: it is on the newly-registered-domains list (week to {day})",
                          {"domain": a.registered_domain, **nd_meta}, t, False))
    kind = platform_kind(a.host)
    if kind == "shorteners":
        out.append(Reason("short_link", "رابط مختصر، الوجهة غير معروفة", "Short link, destination unknown",
                          {"shortener": a.registered_domain}, t, False))
    elif kind:
        own = a.host[: -len(platform_suffix(a.host) or "")].rstrip(".")
        lures = sorted({w for w in _LURE_SPLIT.split(own) if w in LURE_WORDS})  # whole words only
        if lures:
            out.append(Reason("lure_words",
                              "اسم الصفحة على الاستضافة المجانية يستخدم كلمات حسابات ودفع: " + "، ".join(lures),
                              "The page's own name on a free host uses account words: " + ", ".join(lures),
                              {"words": lures, "platform": platform_suffix(a.host)}, t, False))
        out.append(Reason("free_host",
                          "صفحة على استضافة مجانية أو مشتركة: العنوان وحده لا يكفي للتمييز بين الحقيقي والمزيّف",
                          "Page on a free or shared host: the address alone cannot tell real from fake",
                          {"platform": a.private_suffix or a.registered_domain, "kind": kind}, t, False))
    if a.is_ip:
        out.append(Reason("ip_host", "العنوان رقم IP بدلاً من اسم نطاق", "Address is a bare IP number, not a domain name",
                          {"ip": a.host}, t, False))
    kb, kb_meta = known_bad()
    if a.host in kb or a.site in kb:
        out.append(Reason("known_bad", "العنوان مدرج في قائمة تصيّد معروفة", "Address is on a known phishing list",
                          {"host": a.host, **kb_meta}, t, False))
    return out


# ---------- online families (read from OnlineFacts) ----------

def _days_since(iso: str) -> float | None:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).total_seconds() / 86400
    except (ValueError, AttributeError):
        return None


def online_reasons(a: Address, f: OnlineFacts) -> list[Reason]:
    t = now()
    out: list[Reason] = []
    if f.rdap_age_days is not None and f.rdap_age_days <= 30:
        out.append(Reason("new_domain", f"عمر النطاق {f.rdap_age_days} يوماً فقط (سجل RDAP)",
                          f"Domain is only {f.rdap_age_days} days old (RDAP)",
                          {"rdap_age_days": f.rdap_age_days, "domain": a.registered_domain}, t, True))
    if f.cert_first_seen:
        days = _days_since(f.cert_first_seen)
        if days is not None and days <= 30:
            out.append(Reason("young_certificate", f"أول شهادة أمان للموقع ظهرت قبل {max(0, int(days))} يوماً",
                              f"Site's first certificate appeared {max(0, int(days))} days ago (Certificate Transparency)",
                              {"cert_first_seen": f.cert_first_seen}, t, True))
    if f.two_view_difference:
        out.append(Reason("two_view_difference", "الصفحة تُظهر محتوى مختلفاً للخادم وللهاتف (إخفاء)",
                          "Page shows different content to a server and to a phone (cloaking)",
                          {"difference": f.two_view_difference}, t, True))
    if f.live_page_brand:
        claimed = f.live_page_brand.strip().lower()
        for fam in families():
            names = {fam.family, fam.name_en.lower(), fam.name_ar, *fam.brands}
            if claimed in names or any(claimed in n or n in claimed for n in names if len(n) >= 4):
                if not any(a.host == d or a.host.endswith("." + d) for d in fam.domains):
                    out.append(Reason("live_brand_mismatch",
                                      f"الصفحة تدّعي أنها «{fam.name_ar}» لكن النطاق ليس من نطاقاتها الرسمية",
                                      f"Live page claims to be {fam.name_en} but the domain is not one of its official domains",
                                      {"claimed": f.live_page_brand, "family": fam.family}, t, True))
                break
    if f.human_check_wall:
        out.append(Reason("human_check_wall", "الصفحة تختبئ خلف جدار تحقق بشري", "Page hides behind a human-check wall",
                          {}, t, True))
    if f.payee:
        if payee_known(f.payee) is None:
            out.append(Reason("payee_not_in_register", f"المستفيد «{f.payee}» ليس من الحسابات الحكومية المعروفة",
                              f"Payee \"{f.payee}\" is not an account the government is known to use",
                              {"payee": f.payee}, t, True))
    if f.ai_reason is not None:
        r = f.ai_reason
        out.append(Reason("ai_page_description", r.ar, r.en, {**(r.evidence or {}), "ai_code": r.code}, r.time or t, True))
    return out


# ---------- heuristic address score (used when no trained model is available) ----------

_KEYWORDS = ("login", "logon", "signin", "sign-in", "verify", "verification", "secure", "security", "account",
             "update", "confirm", "wallet", "payment", "pay", "bank", "banking", "kyc", "unlock", "suspend",
             "suspended", "refund", "fine", "fines", "billing", "invoice", "auth", "otp", "reward", "gift", "claim",
             "tracking", "delivery", "parcel", "customs", "recover", "validate", "webscr", "password", "support",
             "service", "helpdesk", "portal", "online", "token", "bonus", "prize", "airdrop", "redeem")
_KW_RE = re.compile("|".join(sorted(map(re.escape, _KEYWORDS), key=len, reverse=True)))


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(ch) for ch in set(s)))


def heuristic_score(a: Address) -> tuple[float, dict]:
    host = a.host
    facts: dict = {}
    z = -3.2
    kw_host = len(set(_KW_RE.findall(host)))
    kw_path = len(set(_KW_RE.findall(a.path.lower())))
    if kw_host:
        z += 1.3 * min(kw_host, 3); facts["keywords_in_host"] = kw_host
    if kw_path:
        z += 0.6 * min(kw_path, 2); facts["keywords_in_path"] = kw_path
    # On a shared platform the publisher's own label is the part left of the private suffix.
    own = a.site.split(".")[0] if a.private_suffix else a.label
    own_sub = a.host[: -len(a.site)].rstrip(".") if a.private_suffix else a.subdomain
    hy = own.count("-") + own_sub.count("-")
    if hy:
        z += 0.5 * min(hy, 4); facts["hyphens"] = hy
    digits = sum(c.isdigit() for c in own)
    if digits:
        z += 0.3 * min(digits, 4); facts["digits"] = digits
    nsub = len([s for s in own_sub.split(".") if s])
    if nsub > 1:
        z += 0.5 * min(nsub - 1, 3); facts["subdomains"] = nsub
    if len(host) > 30:
        z += 0.7; facts["host_length"] = len(host)
    if a.is_ip:
        z += 2.5; facts["ip"] = True
    if "xn--" in host:
        z += 1.5; facts["punycode"] = True
    if a.has_userinfo:
        z += 1.5; facts["userinfo"] = True
    kind = platform_kind(host)
    if kind in ("shared_platforms", "tunnels", "dynamic_dns"):
        z += 1.0; facts["free_host"] = kind
    if a.suffix.split(".")[-1] in set(_platforms_suffixes()):
        z += 1.0; facts["risky_suffix"] = a.suffix
    if _entropy(own) > 3.6:
        z += 0.7; facts["entropy"] = round(_entropy(own), 2)
    if any(h["where"] == "host" for h in brand_matches(a)):
        z += 2.0; facts["brand_on_unowned_domain"] = True
    return 1 / (1 + math.exp(-z)), facts


@lru_cache(maxsize=1)
def _platforms_suffixes() -> tuple[str, ...]:
    from .register import platforms
    return tuple(platforms()["suspicious_suffixes"])
