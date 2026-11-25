"""The service against the REAL watch and feeds modules, through their recorded fakes.

Skipped until the watch part is installed; runs automatically after it merges, so any
drift between the service bridges and the real shapes fails here.
"""
import pytest

watch = pytest.importorskip("istibaq.watch")
recorded = pytest.importorskip("istibaq.adapters.recorded")

from istibaq.api import integrations  # noqa: E402


@pytest.fixture
def keys(monkeypatch):
    for k in ("BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
        monkeypatch.setenv(k, "test-key-not-real")


def test_real_run_round_opens_cases(make_client, keys):
    real = integrations.default_watch_round()
    assert real is not None
    client = make_client(watch_round=lambda sink: real(sink, client=recorded.recorded_client()), capture=None)
    run = client.post("/api/watch/run").json()
    assert run["status"] == "done", run
    assert run["results"] > 0
    rnd = real(lambda *a: None, client=recorded.recorded_client()).to_dict()
    assert len(run["cases"]) == len(rnd["suspicious"])
    assert client.get(f"/api/watch/runs/{run['run_id']}/replay").json()["steps"]
    assert client.get("/api/costs").json()["summary"]["total_usd"] > 0


def test_real_feeds_bridge(keys):
    feeds = integrations.feed_counts(client=recorded.recorded_client(), refresh=True)
    assert feeds["status"] == "live"
    assert feeds["certificates"]["feed"] == "certificates"
    assert feeds["new_domains"]["feed"] == "new_domains"
