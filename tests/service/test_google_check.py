"""The on-demand Google and ads check (DataForSEO) through the service.

Never automatic: the scheduled or manual watch round must not reach DataForSEO even
with the switch on. Runs only through recorded fakes; no real DataForSEO call.
"""
import pytest

from istibaq.adapters.recorded import recorded_client
from istibaq.api import integrations


@pytest.fixture
def dfs_on(monkeypatch):
    monkeypatch.setenv("ISTIBAQ_DATAFORSEO", "1")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "team@istibaq.example")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "dfs-SECRET-password")
    for k in ("BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
        monkeypatch.setenv(k, "test-key-not-real")


def test_google_check_is_open_but_off_when_paid_is_off(make_client, dfs_on, monkeypatch):
    c = make_client(token=False, google_client=recorded_client())
    monkeypatch.setenv("ISTIBAQ_PAID", "0")
    assert c.post("/api/google/check").json()["status"] == "off"


def test_switched_off_check_spends_nothing(make_client, monkeypatch):
    monkeypatch.delenv("ISTIBAQ_DATAFORSEO", raising=False)
    log = []
    c = make_client(google_client=recorded_client(log=log))
    out = c.post("/api/google/check").json()
    assert out["status"] == "off" and log == []
    assert c.get("/api/google/status").json()["enabled"] is False
    assert "dataforseo" not in {r["service"] for r in c.get("/api/costs").json()["summary"]["by_service"]}


def test_check_asks_the_five_questions_and_opens_cases_for_ads(make_client, dfs_on):
    log = []
    c = make_client(google_client=recorded_client(log=log))
    out = c.post("/api/google/check").json()
    assert out["status"] == "done", out
    assert out["questions"] == 5 and out["results"] > 0
    assert sum("task_post" in line for line in log) == 5     # one paid search per question
    sources = {cs["source"] for cs in c.get("/api/cases", params={"reveal": True}).json()}
    assert "google_ad/ad" in sources
    assert out["google"]["paid_today"] == 5
    costs = c.get("/api/costs").json()
    dfs = [r for r in costs["summary"]["by_service"] if r["service"] == "dataforseo"][0]
    assert dfs["calls"] == 5 and abs(dfs["usd"] - 0.003) < 1e-9
    entry = next(e for e in costs["entries"] if e["service"] == "dataforseo")
    assert "balance_after" in entry["detail"]
    # asked again within 6 hours: answered from the saved results, no new charge
    log.clear()
    again = c.post("/api/google/check").json()
    assert again["status"] == "done" and not any("dataforseo" in line for line in log)
    assert again["google"]["paid_today"] == 5


def test_status_makes_no_external_call(make_client, dfs_on):
    log = []
    c = make_client(google_client=recorded_client(log=log))
    s = c.get("/api/google/status").json()
    assert s["enabled"] is True and s["daily_cap"] == 30 and s["reserve_usd"] == 0.2
    assert s["cost_per_search_usd"] == 0.0006 and len(s["questions"]) == 5
    assert log == []


def test_voice_action_google_check(make_client, dfs_on):
    c = make_client(google_client=recorded_client())
    out = c.post("/api/voice/tools/google_check", json={}).json()
    assert out["status"] == "done" and out["questions"] == 5


def test_scheduled_round_never_calls_dataforseo(make_client, dfs_on):
    """Even with the switch on and credentials set, the watch round uses only Brave and Places."""
    real = integrations.default_watch_round()
    log = []
    c = make_client(watch_round=lambda sink: real(sink, client=recorded_client(log=log)), capture=None,
                    google_client=recorded_client(log=log))
    run = c.post("/api/watch/run").json()
    assert run["status"] == "done", run
    assert log and not any("dataforseo" in line for line in log)
    assert "dataforseo" not in {r["service"] for r in c.get("/api/costs").json()["summary"]["by_service"]}
