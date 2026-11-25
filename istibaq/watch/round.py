"""One watch round: ask residents' questions, score every result, flag suspects.

The round never writes to a database. It returns a :class:`Round` with
timestamped steps (for replay), every result with its verdict, and the
suspicious ones flagged for the service to open as cases. Scheduling (every
6 hours and on demand) belongs to the service.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from istibaq.adapters.base import AdapterError, MissingKey, now_iso
from istibaq.adapters.contract import OnlineFacts, Verdict
from istibaq.adapters.search import SearchResult

from .questions import QUESTIONS, Question
from .scoring import ScoreFn, get_scorer


class SearchAdapter(Protocol):
    name: str

    def search(self, query: str, lang: str = "en") -> list[SearchResult]: ...


@dataclass
class Step:
    time: str
    action: str     # "ask", "score", "flag", "skip", "error", "open"
    detail: dict

    def to_dict(self) -> dict:
        return {"time": self.time, "action": self.action, "detail": self.detail}


@dataclass
class ScoredResult:
    result: SearchResult
    verdict: Verdict
    suspicious: bool
    topic: str

    def to_dict(self) -> dict:
        return {"result": self.result.to_dict(), "verdict": self.verdict.to_dict(),
                "suspicious": self.suspicious, "topic": self.topic}


@dataclass
class Round:
    id: str
    started_at: str
    finished_at: str = ""
    mode: str = "judging"
    steps: list[Step] = field(default_factory=list)
    results: list[ScoredResult] = field(default_factory=list)

    @property
    def suspicious(self) -> list[ScoredResult]:
        return [r for r in self.results if r.suspicious]

    def step(self, action: str, **detail) -> None:
        self.steps.append(Step(now_iso(), action, detail))

    def to_dict(self) -> dict:
        return {"id": self.id, "started_at": self.started_at, "finished_at": self.finished_at, "mode": self.mode,
                "steps": [s.to_dict() for s in self.steps], "results": [r.to_dict() for r in self.results],
                "suspicious": [r.to_dict() for r in self.suspicious]}


def _judge_listing(res: SearchResult, mode: str, score: ScoreFn, online) -> Verdict:
    """A Maps listing is judged by its name and phone as well as its website (register helplines)."""
    try:
        from istibaq.core.listing import judge_listing
    except ImportError:  # scorer not installed: website only
        return score(res.link, mode=mode, online=online)
    return judge_listing(res.title, phone=res.phone or None, website=res.link or None, mode=mode,
                         online=online if res.link else None)


def is_suspicious(v: Verdict) -> bool:
    """Red always; grey when it carries a reason (e.g. brand look-alike). Green never."""
    return v.verdict == "red" or (v.verdict == "grey" and bool(v.reasons))


def run_round(searchers: Iterable[SearchAdapter], maps: SearchAdapter | None = None,
              questions: Iterable[Question] = QUESTIONS, mode: str = "judging",
              score: ScoreFn | None = None, online_for: callable | None = None) -> Round:
    """Run every question through every searcher (and Maps for questions marked ``maps``).

    ``online_for(link) -> OnlineFacts | None`` may add online facts (e.g. RDAP age)
    before scoring; leave it ``None`` to score from the address alone.
    """
    score = score or get_scorer()
    rnd = Round(uuid.uuid4().hex[:12], now_iso(), mode=mode)
    seen: set[str] = set()
    searchers = list(searchers)
    for q in questions:
        plan = [(s, q.text) for s in searchers] + ([(maps, q.text)] if (maps and q.maps) else [])
        for adapter, text in plan:
            t0 = time.monotonic()
            try:
                found = adapter.search(text, q.lang)
            except MissingKey as e:
                rnd.step("skip", source=adapter.name, query=text, why=str(e))
                continue
            except (AdapterError, OSError, ValueError) as e:
                rnd.step("error", source=adapter.name, query=text, why=str(e)[:200])
                continue
            rnd.step("ask", source=adapter.name, query=text, lang=q.lang, topic=q.topic, results=len(found),
                     ms=int((time.monotonic() - t0) * 1000))
            for res in found:
                key = f"{res.source}|{res.kind}|{res.link or res.title + '|' + res.phone}"
                if key in seen:
                    continue
                seen.add(key)
                online: OnlineFacts | None = None
                if online_for:
                    try:
                        online = online_for(res.link)
                    except Exception as e:  # online facts are optional; never fail the round
                        rnd.step("error", source="online_facts", link=res.link, why=str(e)[:200])
                if res.kind == "maps":
                    v = _judge_listing(res, mode, score, online)
                else:
                    v = score(res.link, mode=mode, online=online)
                sus = is_suspicious(v)
                rnd.results.append(ScoredResult(res, v, sus, q.topic))
                rnd.step("flag" if sus else "score", link=res.link, source=res.source, kind=res.kind,
                         label=res.label, verdict=v.verdict, score=v.score)
    rnd.finished_at = now_iso()
    return rnd


def visible_pages(rnd: Round) -> list[str]:
    """Pages the visible-browser mode may open while showing the work: green register pages only."""
    return [r.result.link for r in rnd.results if r.verdict.verdict == "green"]


def show_work(rnd: Round, open_page: callable) -> Round:
    """Visible-browser mode: open only green register pages (never a suspect) and log each as a step."""
    for link in visible_pages(rnd):
        open_page(link)
        rnd.step("open", link=link, why="showing the work; green register page only")
    return rnd


def record_work(rnd: Round, out_dir, questions: Iterable[Question] = QUESTIONS, views=("computer", "phone"),
                limit: int = 3, speed: float = 3.0, recorder: callable | None = None, **recorder_kw) -> list[dict]:
    """Visible-browser mode, recorded: ONE short overview video per view of the agent asking residents' questions.

    ``recorder`` (default ``istibaq.capture.footage.record_search``) types each of the first ``limit`` questions in
    the search box (on the server: the Fahes search page with real live results, ``fahes_provider(base)``), scrolls
    the results, and on the last one opens only an official register page. The recording is always sped up into an
    MP4, never shown live. Each recording is logged as a ``record`` step. Returns one dict per view.
    """
    from pathlib import Path

    from istibaq.capture.footage import record_search, speed_up
    recorder = recorder or record_search
    out = Path(out_dir)
    texts = [q.text for q in list(questions)[:limit]]
    made: list[dict] = []
    for view in views:
        fx = recorder(texts, out, view=view, **recorder_kw)
        d = fx.to_dict() if hasattr(fx, "to_dict") else dict(fx)
        d["speed"] = speed
        try:
            if d.get("video"):
                d["mp4"] = str(speed_up(d["video"], out / f"overview-{view}.mp4", speed))
        except Exception as e:  # no ffmpeg: keep the raw frames
            d["mp4_error"] = str(e)[:200]
        rnd.step("record", questions=texts, view=view, provider=d.get("provider"), opened=d.get("opened"),
                 robot_checks=d.get("robot_checks"), video=d.get("mp4") or d.get("video"))
        made.append(d)
    return made
