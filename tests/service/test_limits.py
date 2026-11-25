"""Limits on the open desk: the scoring rate and batch size, and the off switches; no voice or run-now caps."""
import httpx



def ok_mint():
    return httpx.MockTransport(lambda req: httpx.Response(200, json={"value": "ek_test_1", "expires_at": 1}))


def test_voice_has_no_session_concurrency_or_budget_caps(make_client):
    c = make_client(token=False, openai_transport=ok_mint())
    ids = [c.post("/api/voice/session").json()["session_id"] for _ in range(5)]
    assert len(set(ids)) == 5  # no "two at once" limit
    c.post("/api/voice/usage", json={"session_id": ids[0], "seconds": 3600})  # an hour: no length or budget cap
    assert c.post("/api/voice/session").status_code == 200
    st = c.get("/api/voice/status").json()
    assert st["sessions_today"] == 6 and st["minutes_today"] == 60.0


def test_voice_and_paid_off_switches(make_client, monkeypatch):
    monkeypatch.setenv("ISTIBAQ_VOICE", "0")
    monkeypatch.setenv("ISTIBAQ_PAID", "0")
    c = make_client(token=False, openai_transport=ok_mint())
    assert c.post("/api/voice/session").status_code == 429
    assert c.post("/api/watch/run").json()["status"] == "off"
    assert "switched off" in c.get("/search/results", params={"q": "x"}, headers={"X-Istibaq-Officer-Token": "officer-test-token"}).text


def test_run_now_is_not_rate_limited(make_client):
    c = make_client(token=False)
    assert c.post("/api/watch/run").json()["status"] == "done"
    assert c.post("/api/watch/run").json()["status"] == "done"
    assert c.post("/api/watch/run", params={"wait": False}).json()["status"] == "started"


def test_scoring_rate_per_visitor_and_batch_size(make_client, monkeypatch):
    monkeypatch.setenv("ISTIBAQ_SCORE_PER_MINUTE", "3")
    monkeypatch.setenv("ISTIBAQ_BATCH_MAX", "2")
    c = make_client(token=False)
    one = {"fly-client-ip": "198.51.100.7"}
    for _ in range(3):
        assert c.post("/api/score", json={"link": "a.example"}, headers=one).status_code == 200
    assert c.post("/api/score", json={"link": "a.example"}, headers=one).status_code == 429
    assert c.post("/api/score", json={"link": "a.example"}, headers={"fly-client-ip": "198.51.100.8"}).status_code == 200
    big = c.post("/api/score/batch", json={"links": ["a.example", "b.example", "c.example"]}, headers={"fly-client-ip": "198.51.100.9"})
    assert big.status_code == 413


def test_verify_an_edited_record_address(make_client):
    c = make_client(token=False)
    cid = c.post("/api/cases", json={"link": "https://tamm-fines-pay.example/login"}).json()["id"]
    sha = c.post(f"/api/cases/{cid}/seal").json()["sha256"]
    same = c.post(f"/api/cases/{cid}/verify", json={}).json()
    assert same["ok"] is True and same["fingerprint_now"] == sha
    bad = c.post(f"/api/cases/{cid}/verify", json={"address": "https://tamm-fines-pey.example/login"}).json()
    assert bad["ok"] is False and bad["fingerprint_now"] != sha
