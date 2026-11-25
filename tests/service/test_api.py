import json

import httpx

from istibaq.cases import service as cases


def test_health_and_page(client):
    h = client.get("/health").json()
    assert h["ok"] is True and h["model_version"]
    page = client.get("/")
    assert page.status_code == 200 and 'dir="rtl"' in page.text


def test_score_one_and_batch_follow_contract(make_client):
    client = make_client(token=False)  # judges need no token for scoring
    v = client.post("/api/score", json={"link": "https://www.adpolice.gov.ae/"}).json()
    assert v["verdict"] == "green" and v["is_fraud"] is False
    out = client.post("/api/score/batch", json={"links": ["https://tamm-fines-pay.example/login", "", "bit.ly/abc"]}).json()
    assert out["count"] == 2
    for v in out["results"]:
        assert set(v) >= {"link", "verdict", "is_fraud", "score", "reasons", "model_version", "scored_at"}
        assert v["verdict"] in ("green", "grey", "red") and 0 <= v["score"] <= 1
        for r in v["reasons"]:
            assert set(r) >= {"code", "ar", "en", "evidence", "time", "online"}


def test_watch_round_to_case_capture_seal_approve(client):
    run = client.post("/api/watch/run").json()
    assert run["status"] == "done" and run["results"] == 3
    assert len(run["cases"]) == 2  # the official result never becomes a case

    reds = [c for c in client.get("/api/cases", params={"reveal": True}).json() if c["verdict"] == "red"]
    assert reds, "the look-alike ad should be red"
    cid = reds[0]["id"]
    case = client.get(f"/api/cases/{cid}").json()
    # captured during the round, and re-scored with the capture's facts
    assert case["capture"]["facts"]["two_view_difference"]
    assert "two_view_difference" in {r["code"] for r in case["verdict_full"]["reasons"]}

    rec = client.post(f"/api/cases/{cid}/seal").json()
    assert len(rec["sha256"]) == 64 and rec["verification"]["ok"] is True
    body = rec["body"]
    assert body["title_ar"] and body["chain"] == ["https://bit.ly/x", case["link"]]
    assert {s["sha256"] for s in body["captures"]} == {"cd" * 32, "ef" * 32}
    assert body["differences"] and body["capture_full"]["server"]["title"] == "Not found"
    assert body["verdict_full"]["is_fraud"] is True

    assert client.post(f"/api/cases/{cid}/approve", json={"method": "click", "officer": "O-7"}).status_code == 200
    rec = client.get(f"/api/cases/{cid}").json()["record"]
    a = rec["approvals"][0]
    assert a["method"] == "click" and a["officer"] == "O-7" and a["verified"] and len(a["approval_sha"]) == 64
    pkg = client.get(f"/api/cases/{cid}/takedown").json()
    assert pkg["sent"] is False and pkg["record_sha256"] == rec["sha256"] and pkg["chain"]


def test_capture_endpoint_rescoring(client):
    cid = client.post("/api/cases", json={"link": "https://tamm-fines-pay.example/login"}).json()["id"]
    cap = client.post(f"/api/cases/{cid}/capture").json()
    assert cap["facts"]["redirect_chain"]
    shown = client.get(f"/api/cases/{cid}", params={"reveal": True}).json()
    assert "two_view_difference" in {r["code"] for r in shown["verdict_full"]["reasons"]}
    paths = [s["path"] for v in ("server", "phone") for s in shown["capture"][v]["screenshots"]]
    assert paths == ["server-0.png", "phone-0.png"]  # relative to the case's capture folder


def test_failed_watch_round_is_marked_failed(make_client):
    def broken(cost_sink):
        raise RuntimeError("search adapter exploded")
    client = make_client(watch_round=broken)
    run = client.post("/api/watch/run").json()
    assert run["status"] == "failed" and "exploded" in run["error"]
    last = client.get("/api/watch/last").json()
    assert last["finished_at"] and last["summary"]["status"] == "failed"


def test_approve_requires_seal(client):
    cid = client.post("/api/cases", json={"link": "https://adpolice-verify-pay.test/"}).json()["id"]
    assert client.post(f"/api/cases/{cid}/approve", json={"method": "voice"}).status_code == 409


def test_tamper_detection_record(client):
    cid = client.post("/api/cases", json={"link": "https://tamm-fines-pay.example/login"}).json()["id"]
    client.post(f"/api/cases/{cid}/capture")
    client.post(f"/api/cases/{cid}/seal")
    store = client.app.state.store
    row = store.one("SELECT id, body_json FROM records WHERE case_id=?", (cid,))
    body = json.loads(row["body_json"])
    body["capture_full"]["phone"]["screenshots"][0]["sha256"] = "00" * 32  # swap a screenshot
    store.execute("UPDATE records SET body_json=? WHERE id=?", (json.dumps(body, ensure_ascii=False), row["id"]))
    ver = client.get(f"/api/cases/{cid}", params={"reveal": True}).json()["record"]["verification"]
    assert ver["ok"] is False and ver["en"].startswith("Verification failed") and ver["ar"]
    assert client.post(f"/api/cases/{cid}/approve", json={"method": "click"}).status_code == 409


def test_tamper_detection_approval(client):
    cid = client.post("/api/cases", json={"link": "https://tamm-fines-pay.example/login"}).json()["id"]
    client.post(f"/api/cases/{cid}/seal")
    client.post(f"/api/cases/{cid}/approve", json={"method": "voice", "officer": "O-1"})
    client.app.state.store.execute("UPDATE approvals SET officer='someone-else'")
    rec = client.get(f"/api/cases/{cid}", params={"reveal": True}).json()["record"]
    assert rec["approvals"][0]["verified"] is False
    assert rec["verification"]["ok"] is False


def test_grey_names_hidden_until_asked(client):
    store = client.app.state.store
    reason = {"code": "brand_mismatch", "ar": "يشبه", "en": "Looks like", "time": "t", "online": False,
              "evidence": {"host": "shop.example", "chain": ["https://shop.example/"]}}
    cid = cases.open_case(store, {"link": "https://shop.example/", "verdict": "grey", "score": 0.6,
                                  "reasons": [reason]}, "watch")
    cases.attach_capture(store, cid, {"final_url": "https://shop.example/"})
    for path in ("/api/cases", f"/api/cases/{cid}"):
        assert "shop.example" not in client.get(path).text
    shown = client.get(f"/api/cases/{cid}").json()
    assert shown["reasons"] == [{"code": "brand_mismatch", "ar": "يشبه", "en": "Looks like"}]
    assert "shop.example" not in client.post("/api/voice/tools/show_case", json={"case_id": cid}).text
    assert client.get(f"/api/cases/{cid}", params={"reveal": True}).json()["link"] == "https://shop.example/"


def test_grey_names_masked_in_replay(client):
    run = client.post("/api/watch/run").json()
    rid = run["run_id"]
    grey_links = [s["detail"]["link"] for s in client.get(f"/api/watch/runs/{rid}/replay", params={"reveal": True}).json()["steps"]
                  if s["detail"].get("verdict") == "grey"]
    masked = client.get(f"/api/watch/runs/{rid}/replay").text
    voice = client.post("/api/voice/tools/show_run", json={"run_id": rid}).text
    for link in grey_links:
        assert link not in masked and link not in voice


def test_not_a_scam_feedback(client, monkeypatch):
    from istibaq.api import integrations
    calls = []
    monkeypatch.setattr(integrations, "register_apply_edit", lambda *a: calls.append(a) or True)
    cid = client.post("/api/cases", json={"link": "https://tamm-fines-pay.example/login"}).json()["id"]
    out = client.post(f"/api/cases/{cid}/mark", json={"status": "not_scam", "officer": "O-7"}).json()
    assert out["register_applied"] is True and calls[0][0] == "https://tamm-fines-pay.example/login"
    edits = client.get("/api/register/edits").json()
    assert edits[0]["status"] == "not_scam" and edits[0]["source"] == "officer:O-7"
    assert client.get(f"/api/cases/{cid}").json()["status"] == "not_scam"


def test_the_desk_is_open_and_only_admin_needs_the_token(make_client):
    """No passcode for the public: desk actions work for any visitor; the token is only for maintenance."""
    anon = make_client(token=False)
    assert anon.post("/api/register/edits", json={"address": "adp0lice-gov.example", "status": "licensed",
                                                  "source": "anyone"}).status_code == 401
    assert anon.post("/api/drills", json={"address": "d.example", "published_at": "2026-11-24T10:00:00Z"}).status_code == 401
    assert anon.post("/api/costs", json={"service": "x", "amount_usd": 1}).status_code == 401
    cid = anon.post("/api/cases", json={"link": "https://tamm-fines-pay.example/login"}).json()["id"]
    assert anon.post(f"/api/cases/{cid}/seal").status_code == 200
    assert anon.post(f"/api/cases/{cid}/approve", json={"method": "click"}).status_code == 200
    assert anon.get(f"/api/cases/{cid}/takedown").status_code == 200
    assert anon.get(f"/api/cases/{cid}?reveal=true").status_code == 200
    assert anon.post("/api/watch/run").json()["status"] == "done"
    assert anon.post("/api/score", json={"link": "https://x.example/"}).status_code == 200


def test_admin_refused_when_token_unset(make_client, monkeypatch):
    c = make_client()
    monkeypatch.delenv("ISTIBAQ_OFFICER_TOKEN")
    assert c.post("/api/drills", json={"address": "d.example", "published_at": "2026-11-24T10:00:00Z"}).status_code == 503


def test_bad_register_status_rejected_and_restart_survives(make_client, monkeypatch):
    from istibaq.api import integrations
    c = make_client(db="r.db")
    for status in ("official", "bogus"):
        r = c.post("/api/register/edits", json={"address": "adp0lice-gov.example", "status": status, "source": "o"})
        assert r.status_code == 422
    assert c.get("/api/register/edits").json() == []

    def refuse(address, status, source, note):
        raise ValueError(f"unknown register status: {status}")
    monkeypatch.setattr(integrations, "register_apply_edit", refuse)
    assert c.post("/api/register/edits", json={"address": "a.example", "status": "licensed",
                                               "source": "o"}).status_code == 422
    assert c.get("/api/register/edits").json() == []
    # a bad row already in the database must not stop the app from starting
    c.app.state.store.execute("INSERT INTO register_edits (address, status, source, created_at) VALUES "
                              "('a.example','bogus','old','2026-11-25T00:00:00Z')")
    again = make_client(db="r.db")
    assert again.get("/health").status_code == 200


def test_cost_logging_and_projection(client):
    client.post("/api/watch/run")
    costs = client.get("/api/costs", params={"runs_per_day": 4}).json()
    services = {r["service"] for r in costs["summary"]["by_service"]}
    assert {"brave", "places"} <= services
    assert abs(costs["summary"]["total_usd"] - 0.018) < 1e-9
    assert costs["summary"]["projection"]["monthly_usd"] > 6.0


def test_voice_mint_never_leaks_key(client, seen, fake_key):
    r = client.post("/api/voice/session")
    assert r.status_code == 200
    assert r.json()["client_secret"] == "ek_ephemeral_abc"
    assert fake_key not in r.text
    sent = seen[0]
    assert sent.headers["authorization"] == f"Bearer {fake_key}"
    assert json.loads(sent.content)["session"]["model"] == "gpt-realtime-2.1"
    costs = client.get("/api/costs").json()
    mint = [e for e in costs["entries"] if e["service"] == "openai_realtime"][0]
    assert mint["amount_usd"] > 0 and mint["detail"]["estimate"] is True
    for path in ["/health", "/api/summary", "/api/agents", "/api/costs", "/api/feeds", "/api/scorecard"]:
        assert fake_key not in client.get(path).text


def test_voice_mint_without_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    assert client.post("/api/voice/session").status_code == 503


def test_voice_tools(client):
    run = client.post("/api/voice/tools/run_now", json={}).json()
    red = [c for c in client.get("/api/cases", params={"reveal": True}).json() if c["verdict"] == "red"][0]["id"]
    assert client.post("/api/voice/tools/show_case", json={"case_id": red}).json()["id"] == red
    assert client.post("/api/voice/tools/check_address", json={"address": "https://www.adpolice.gov.ae"}).json()["verdict"] == "green"
    client.post("/api/voice/tools/seal", json={"case_id": red})
    rec = client.post("/api/voice/tools/approve", json={"case_id": red, "officer": "O-9"}).json()
    assert rec["approvals"][0]["method"] == "voice"
    assert client.post("/api/voice/tools/show_run", json={}).json()["run"]["id"] == run["run_id"]
    agents = {a["agent"] for a in client.post("/api/voice/tools/agents", json={}).json()}
    assert agents == {"watch", "register", "check", "capture", "seal", "drill", "scale"}
    assert "cases_by_status" in client.post("/api/voice/tools/summary", json={}).json()
    assert client.post("/api/voice/tools/scale", json={}).status_code == 200
    assert client.post("/api/voice/tools/nope", json={}).status_code == 404


def test_drills(client):
    client.post("/api/drills", json={"address": "drill.example", "published_at": "2026-11-24T10:00:00Z",
                                     "found_at": "2026-11-24T10:12:00Z", "feed": "ct"})
    client.post("/api/drills", json={"address": "drill2.example", "published_at": "2026-11-24T11:00:00Z",
                                     "found_at": "2026-11-24T11:30:00Z", "feed": "ct"})
    rep = client.get("/api/drills").json()
    assert rep["median_minutes"] == 21.0 and rep["slowest_minutes"] == 30.0


def test_watch_unavailable_is_honest(make_client):
    c = make_client(db="u.db", watch_round=None, capture=None)
    assert c.post("/api/watch/run").json()["status"] == "unavailable"
    assert c.post("/api/cases/1/capture").status_code == 503


def test_feed_lookalike_names_masked(make_client):
    def feeds():
        return {"status": "live", "certificates": {"feed": "certificates", "lookalikes": [
            {"name": "tamm-grey.example", "brand": "TAMM", "score": 0.6, "verdict": "grey"},
            {"name": "tamm-red.example", "brand": "TAMM", "score": 0.95, "verdict": "red"}]},
            "new_domains": {"feed": "new_domains", "lookalikes": [
                {"name": "adcb-grey.example", "brand": "ADCB", "score": 0.5, "verdict": "grey"}]}}
    officer = make_client(feeds=feeds)
    anon = make_client(db="a.db", token=False, feeds=feeds)
    for text in (anon.get("/api/feeds").text, officer.get("/api/feeds").text,
                 officer.post("/api/voice/tools/scale", json={}).text):
        assert "tamm-grey.example" not in text and "adcb-grey.example" not in text
        assert "tamm-red.example" in text
    assert "tamm-grey.example" in officer.get("/api/feeds", params={"reveal": True}).text
    assert "adcb-grey.example" in officer.post("/api/voice/tools/scale", json={"reveal": True}).text


def test_import_fallback_only_for_the_missing_module(monkeypatch):
    import importlib

    import pytest

    from istibaq.api import integrations

    def fake_import(name):
        raise ModuleNotFoundError("No module named 'playwright'", name="playwright")
    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(ModuleNotFoundError):
        integrations._try("istibaq.capture")

    def missing(name):
        raise ModuleNotFoundError(f"No module named '{name}'", name="istibaq.capture")
    monkeypatch.setattr(importlib, "import_module", missing)
    assert integrations._try("istibaq.capture") is None


def test_voice_session_uses_the_one_shared_source():
    """The engine mints with the same instructions, voice and tools as the screens (istibaq/voice/session.json)."""
    import json
    from pathlib import Path
    from istibaq.voice import mint as m
    shared = json.loads((Path(m.__file__).with_name("session.json")).read_text(encoding="utf-8"))
    cfg = m.session_config("gpt-realtime-2.1")
    assert cfg["instructions"] == shared["instructions"]
    assert cfg["audio"]["output"]["voice"] == shared["voice"] == "cedar"
    assert [t["name"] for t in cfg["tools"]] == [t["name"] for t in shared["tools"]]
    assert "never repeat it after a task" in cfg["instructions"] and "masculine" not in cfg["instructions"]


def test_fahes_search_page_shows_real_results_with_verdict_chips(client, monkeypatch):
    from istibaq.api.app import TOKEN_HEADER
    from istibaq.capture import searchpage
    assert "name='q'" in client.get("/search").text
    assert client.get("/search/results", params={"q": "pay fine"}, headers={TOKEN_HEADER: "wrong"}).status_code == 401  # paid
    monkeypatch.setattr(searchpage, "live_results", lambda q, **kw: [
        {"title": "Pay traffic fines", "link": "https://www.tamm.abudhabi/fines", "snippet": "TAMM", "kind": "organic", "verdict": "green"},
        {"title": "Fines office", "link": "https://fines.example/", "snippet": "Abu Dhabi · 02 000 0000", "kind": "maps", "verdict": "grey"}])
    page = client.get("/search/results", params={"q": "pay fine", "maps": True},
                      headers={TOKEN_HEADER: "officer-test-token"}).text
    assert "Real results · Fahes search page" in page
    assert "class='r' href='https://www.tamm.abudhabi/fines'" in page and "class='r maps'" in page
    assert "Official" in page and "Not official, not accused" in page


def test_round_footage_is_kept_seven_days(tmp_path):
    import os
    import time
    from istibaq.api.watchrun import prune_footage
    old, new = tmp_path / "round-1", tmp_path / "round-2"
    old.mkdir(); new.mkdir()
    t = time.time()
    os.utime(old, (t - 8 * 86400, t - 8 * 86400))
    assert prune_footage(tmp_path, now=t) == ["round-1"]
    assert new.exists() and not old.exists()


def test_round_overview_records_on_the_fahes_search_page(tmp_path, monkeypatch):
    from istibaq.api import watchrun
    from istibaq.store.db import Store
    monkeypatch.setenv("ISTIBAQ_FOOTAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ISTIBAQ_PUBLIC_URL", "https://fahes.example")
    calls = []

    def fake(qs, out, view, **kw):
        calls.append((view, kw["providers"], kw["provider_urls"]["fahes"]["home"], kw["trusted_origins"]))
        return {"question": " | ".join(qs), "view": view, "video": "", "provider": "fahes", "robot_checks": []}

    store = Store(str(tmp_path / "db.sqlite"))
    run_id = store.execute("INSERT INTO watch_runs (trigger, started_at) VALUES (?,?)", ("test", "now"))
    made = watchrun.record_round_overview(store, run_id, recorder=fake)
    assert [c[0] for c in calls] == ["computer", "phone"]
    assert calls[0][1:] == (("fahes",), "https://fahes.example/search", ("https://fahes.example",))
    assert len(made) == 2


def test_capture_asks_the_ai_layer_for_the_claimed_brand_when_enabled(make_client, monkeypatch):
    from istibaq.api import integrations

    def no_brand_capture(link, out_dir):
        view = {"name": "phone", "title": "", "text": "Pay your fine with your card", "screenshots": [], "hops": []}
        return {"link": link, "server": {**view, "name": "server", "text": ""}, "phone": view, "differences": [],
                "facts": {"redirect_chain": None, "live_page_brand": None, "two_view_difference": None}}
    calls = []

    def fake_ai(link, text):
        calls.append(text)
        return {"live_page_brand": "TAMM"}
    monkeypatch.setattr(integrations, "ai_page_facts", fake_ai)
    client = make_client(capture=no_brand_capture)
    cid = client.post("/api/cases", json={"link": "https://x7k2.pages.dev/"}).json()["id"]
    client.post(f"/api/cases/{cid}/capture")
    shown = client.get(f"/api/cases/{cid}", params={"reveal": True}).json()
    assert calls == ["Pay your fine with your card"]
    assert "live_brand_mismatch" in {r["code"] for r in shown["verdict_full"]["reasons"]}


def test_ai_page_facts_is_off_without_the_switch_and_key(monkeypatch):
    from istibaq.api import integrations
    monkeypatch.delenv("ISTIBAQ_AI_LAYER", raising=False)
    assert integrations.ai_page_facts("https://x.test/", "text") == {}


def test_phone_only_maps_listing_becomes_a_case(make_client):
    listing = {"result": {"source": "places", "kind": "maps", "query": "q", "position": 1, "title": "Abu Dhabi Police Fines",
                          "link": "", "snippet": "", "label": "live", "phone": "050 555 0199"},
               "verdict": {"link": "maps:Abu Dhabi Police Fines", "verdict": "grey", "is_fraud": False, "score": 0.7,
                           "reasons": [{"code": "listing_phone_not_official", "ar": "x", "en": "y", "evidence": {},
                                        "time": "2026-11-25T00:00:00Z", "online": True}],
                           "model_version": "m", "scored_at": "2026-11-25T00:00:00Z"},
               "suspicious": True, "topic": "helplines"}

    def one_listing(cost_sink):
        return {"id": "r1", "started_at": "2026-11-25T00:00:00Z", "finished_at": "2026-11-25T00:00:01Z",
                "steps": [], "results": [listing], "suspicious": [listing]}
    client = make_client(watch_round=one_listing)
    run = client.post("/api/watch/run").json()
    assert run["status"] == "done" and len(run["cases"]) == 1, run


def _ai_model(log, cost=0.3):
    import json as _json

    def handler(request):
        sent = _json.loads(_json.loads(request.content)["messages"][1]["content"])["links"]
        log.append([it["address"] for it in sent])
        items = [{"id": it["id"], "verdict": "fake", "confidence": 0.95, "brand": "", "brand_domain": "",
                  "why_en": "fines scam", "why_ar": "احتيال مخالفات"} for it in sent]
        return httpx.Response(200, json={"choices": [{"message": {"content": _json.dumps({"items": items})}}],
                                         "usage": {"cost": cost}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_live_scoring_uses_the_ai_second_opinion_with_a_daily_cap(make_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ISTIBAQ_AI_SECOND", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-SECRET")
    monkeypatch.setenv("ISTIBAQ_AI_CACHE", str(tmp_path / "ai_cache.jsonl"))
    monkeypatch.setenv("ISTIBAQ_AI_DAILY_USD", "1.0")
    log = []
    client = make_client(ai_client=_ai_model(log))
    v = client.post("/api/score", json={"link": "fines-portal.example"}).json()
    assert v["is_fraud"] and "ai_second_opinion" in {r["code"] for r in v["reasons"]}
    out = client.post("/api/score/batch", json={"links": ["fines-office.example", "https://www.tamm.abudhabi/"]}).json()
    assert out["results"][1]["verdict"] == "green"
    assert log == [["fines-portal.example"], ["fines-office.example"]]
    costs = client.get("/api/costs").json()
    assert "sk-or-SECRET" not in repr(costs)
    # $0.60 spent today: a next call (0.3, with 1.5x headroom) could pass the $1 cap, so pure code, silently
    w = client.post("/api/score", json={"link": "fines-service.example"}).json()
    assert not w["is_fraud"] and len(log) == 2


def test_live_scoring_is_pure_code_when_the_ai_is_off(make_client, monkeypatch):
    monkeypatch.delenv("ISTIBAQ_AI_SECOND", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-SECRET")
    log = []
    v = make_client(ai_client=_ai_model(log)).post("/api/score", json={"link": "fines-portal.example"}).json()
    assert not v["is_fraud"] and log == []
