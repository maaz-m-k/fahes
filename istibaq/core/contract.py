"""Output contract shared by every part of the Istibaq engine."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass
class Reason:
    code: str            # stable machine code, e.g. "brand_mismatch"
    ar: str              # Arabic text (shown first)
    en: str              # English text
    evidence: dict       # facts behind it (registration age, cert time, brand, hop...)
    time: str            # ISO-8601 UTC when the fact was observed
    online: bool         # True if it needed the internet

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OnlineFacts:       # every field optional; None means unknown
    rdap_age_days: int | None = None
    cert_first_seen: str | None = None        # ISO-8601 UTC
    redirect_chain: list[str] | None = None   # every hop, first to last
    two_view_difference: str | None = None    # what differed between server and phone views
    live_page_brand: str | None = None        # brand the live page claims to be
    human_check_wall: bool | None = None
    payee: str | None = None                  # account or collector named on the page
    ai_reason: Reason | None = None           # optional AI layer: may ADD a reason, never clear a link

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Verdict:
    link: str
    verdict: Literal["green", "grey", "red"]
    is_fraud: bool
    score: float          # 0 to 1
    reasons: list[Reason] = field(default_factory=list)
    model_version: str = ""
    scored_at: str = ""   # ISO-8601 UTC

    def to_dict(self) -> dict:
        return {
            "link": self.link,
            "verdict": self.verdict,
            "is_fraud": self.is_fraud,
            "score": self.score,
            "reasons": [r.to_dict() for r in self.reasons],
            "model_version": self.model_version,
            "scored_at": self.scored_at,
        }
