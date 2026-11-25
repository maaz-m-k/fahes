"""The shared output contract, imported from the scorer's module.

Until ``istibaq.core.contract`` is on ``main`` this file carries an identical
stand-in so the watch can be built and tested on its own branch.
"""
from __future__ import annotations

try:  # pragma: no cover - exercised once the scorer lands
    from istibaq.core.contract import OnlineFacts, Reason, Verdict  # type: ignore
except ImportError:  # stand-in, same fields as the shared contract
    from dataclasses import asdict, dataclass, field
    from typing import Literal

    @dataclass
    class Reason:  # type: ignore[no-redef]
        code: str
        ar: str
        en: str
        evidence: dict
        time: str
        online: bool

        def to_dict(self) -> dict:
            return asdict(self)

    @dataclass
    class OnlineFacts:  # type: ignore[no-redef]
        rdap_age_days: int | None = None
        cert_first_seen: str | None = None
        redirect_chain: list[str] | None = None
        two_view_difference: str | None = None
        live_page_brand: str | None = None
        human_check_wall: bool | None = None
        payee: str | None = None
        ai_reason: Reason | None = None

        def to_dict(self) -> dict:
            return asdict(self)

    @dataclass
    class Verdict:  # type: ignore[no-redef]
        link: str
        verdict: Literal["green", "grey", "red"]
        is_fraud: bool
        score: float
        reasons: list[Reason] = field(default_factory=list)
        model_version: str = ""
        scored_at: str = ""

        def to_dict(self) -> dict:
            return asdict(self)

__all__ = ["OnlineFacts", "Reason", "Verdict"]
