"""Which official UAE brand a live page shows, read from the Genuine Register (never from a model).

``page_brand(title, text)`` looks for a register family's English or Arabic name, or one of its brand
words as a whole word, in the page title and text. The scorer then compares that brand's official
domains with the page's address (``live_brand_mismatch``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .register import families

_WORD = re.compile(r"[a-z0-9؀-ۿ]+")
# Brand words too common in ordinary text to count alone on a page.
_PAGE_STOP = frozenset({"fab", "dge", "icp", "eand"})


@dataclass(frozen=True)
class PageBrand:
    family: str
    brand: str
    name_en: str


def _find(hay: str, joined: str) -> PageBrand | None:
    low = hay.lower()
    words = set(_WORD.findall(low))
    for fam in families():
        if not fam.official:
            continue
        for b in sorted(fam.brands, key=len, reverse=True):
            if b in _PAGE_STOP:
                continue
            if b in words or (len(b) >= 6 and b in joined):
                return PageBrand(fam.family, b, fam.name_en)
        if (len(fam.name_en) >= 6 and fam.name_en.lower() in low) or (fam.name_ar and len(fam.name_ar) >= 4 and fam.name_ar in hay):
            return PageBrand(fam.family, fam.family, fam.name_en)
    return None


def page_brand(title: str, text: str) -> PageBrand | None:
    """The title decides first (it names who the page claims to be); the body text only when it names none."""
    title = title or ""
    return (_find(title, "".join(_WORD.findall(title.lower())))
            or _find((text or "")[:20000], ""))
