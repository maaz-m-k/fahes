"""Service test fixtures.

The fakes below follow the REAL shapes of ``istibaq.watch.Round.to_dict()`` and
``istibaq.capture.Capture.to_dict()``. When the watch module is installed,
``test_real_watch.py`` also runs the real ``run_round`` through its recorded fakes,
so shape drift is caught.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from istibaq.api import integrations
from istibaq.api.app import TOKEN_HEADER, create_app

FAKE_KEY = "sk-test-REAL-KEY-must-never-leak-0123456789"
OFFICER_TOKEN = "officer-test-token"


def _scored(link, source, kind, mode="officer"):
    v = integrations.score(link, mode=mode)
    return {"result": {"source": source, "kind": kind, "query": "q", "position": 1, "title": "t",
                       "link": link, "snippet": "", "label": "borrowed" if source.startswith("google") else "live"},
            "verdict": v, "suspicious": v["verdict"] == "red" or (v["verdict"] == "grey" and bool(v["reasons"])),
            "topic": "fines"}


def recorded_watch_round(cost_sink):
    """Same shape as Round.to_dict(): one ad, one Maps listing, one official result."""
    cost_sink("brave", 0.001, {"query": "دفع مخالفات أبوظبي"})
    cost_sink("places", 0.017, {"query": "abu dhabi police fines"})
    results = [_scored("https://tamm-fines-pay.example/login", "google_ad", "ad"),
               _scored("https://adpolice-verify-pay.test/", "places", "maps"),
               _scored("https://www.adpolice.gov.ae/", "brave", "organic")]
    steps = [{"time": "2026-11-25T00:00:00Z", "action": "ask", "detail": {"source": "brave", "query": "q", "results": 2}},
             {"time": "2026-11-25T00:00:01Z", "action": "ask", "detail": {"source": "places", "query": "q", "results": 1}}]
    steps += [{"time": "2026-11-25T00:00:02Z", "action": "flag" if r["suspicious"] else "score",
               "detail": {"link": r["result"]["link"], "verdict": r["verdict"]["verdict"], "label": "x"}}
              for r in results]
    return {"id": "abc123", "started_at": "2026-11-25T00:00:00Z", "finished_at": "2026-11-25T00:00:03Z",
            "mode": "officer", "steps": steps, "results": results,
            "suspicious": [r for r in results if r["suspicious"]]}


def recorded_capture(link, out_dir):
    """Same shape as Capture.to_dict()."""
    def view(name, title, err=""):
        return {"name": name, "user_agent": "ua", "hops": [{"url": "https://bit.ly/x", "status": 301, "kind": "http"},
                                                           {"url": link, "status": 200, "kind": "final"}],
                "final_url": link, "title": title, "text": "", "html_sha256": "ab" * 32, "human_check_wall": False,
                "wall_markers": [], "error": err,
                "screenshots": [{"url": link, "path": f"{out_dir}/{name}-0.png", "sha256": ("cd" if name == "phone" else "ef") * 32,
                                 "time": "2026-11-25T00:00:05Z"}]}
    return {"link": link, "started_at": "2026-11-25T00:00:04Z", "finished_at": "2026-11-25T00:00:09Z",
            "server": view("server", "Not found"), "phone": view("phone", "TAMM payment"),
            "differences": ["title differs: server 'Not found', phone 'TAMM payment'"],
            "saw_through": ["hidden from server view", "redirect chain followed"],
            "facts": {"rdap_age_days": None, "cert_first_seen": None,
                      "redirect_chain": ["https://bit.ly/x", link],
                      "two_view_difference": "server saw 'Not found', phone saw a payment form",
                      "live_page_brand": "TAMM", "human_check_wall": False, "payee": None, "ai_reason": None}}


def recorded_feeds():
    return {"status": "live", "at": "2026-11-25T00:00:00Z",
            "certificates": {"feed": "certificates", "label": "live", "source": "CT log (recorded)", "total": 120,
                             "rate_per_hour": 4800.0, "lookalikes": [], "at": "2026-11-25T00:00:00Z"},
            "new_domains": {"feed": "new_domains", "label": "borrowed", "source": "recorded", "total": 3,
                            "rate_per_hour": None, "lookalikes": [], "at": "2026-11-25T00:00:00Z"}}


def openai_transport(seen):
    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"value": "ek_ephemeral_abc", "expires_at": 1795560000,
                                         "session": {"type": "realtime", "model": "gpt-realtime-2.1"}})
    return httpx.MockTransport(handler)


@pytest.fixture
def recorded_capture_fn():
    return recorded_capture


@pytest.fixture
def fake_key():
    return FAKE_KEY


@pytest.fixture
def seen():
    return []


@pytest.fixture
def make_client(tmp_path, monkeypatch, seen):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ISTIBAQ_OFFICER_TOKEN", OFFICER_TOKEN)
    monkeypatch.setenv("ISTIBAQ_CAPTURE_DIR", str(tmp_path / "captures"))
    clients = []

    def make(db="t.db", token=True, **kw):
        opts = dict(schedule=False, watch_round=recorded_watch_round, capture=recorded_capture,
                    openai_transport=openai_transport(seen), feeds=recorded_feeds, phish_feed=None)
        opts.update(kw)
        c = TestClient(create_app(str(tmp_path / db), **opts),
                       headers={TOKEN_HEADER: OFFICER_TOKEN} if token else {})
        c.__enter__()
        c.app.state.feeds.refresh()  # the background count, done now so the tests read numbers
        clients.append(c)
        return c
    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()
