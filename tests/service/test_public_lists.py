"""Real red cases from public scam lists (OpenPhish; PhishTank only without a key), fewer grey cases,
and the scale numbers served at once from the background count. Recorded feeds only; no network."""
from pathlib import Path

import httpx

from istibaq.adapters import phishfeed
from istibaq.api import watchrun
from istibaq.api.feedcache import FeedCache
from istibaq.store.db import dumps, now_iso

FEED = (Path(__file__).parent.parent / "fixtures" / "publiclists" / "openphish_feed.txt").read_text()


def lists_client(phishtank_status=403):
    def handler(req: httpx.Request):
        if req.url.host == "openphish.com":
            return httpx.Response(200, text=FEED)
        return httpx.Response(phishtank_status, text="key required")
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pick_prefers_uae_brands_one_link_a_host_and_skips_known():
    links, facts = phishfeed.fetch(client=lists_client(), limit=4)
    assert facts["OpenPhish"] == {"links": 6} and facts["PhishTank"] == {"links": 0}
    assert [x.brand_word for x in links[:2]] == ["tamm", "adcb"]
    assert len({phishfeed._host(x.link) for x in links}) == len(links) == 4
    again, _ = phishfeed.fetch(client=lists_client(), limit=10, seen={links[0].link})
    assert links[0].link not in [x.link for x in again]
    assert links[0].source == "publiclist/openphish"


def test_a_list_that_is_down_is_reported_not_invented():
    def handler(req):
        return httpx.Response(503)
    links, facts = phishfeed.fetch(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert links == [] and facts["OpenPhish"] == {"error": "HTTPStatusError"}


def test_run_now_reads_the_lists_keeps_red_cases_and_records_dead_links(make_client, recorded_capture_fn):
    def capture(link, out_dir):
        cap = recorded_capture_fn(link, out_dir)
        if "dead-link" in link:
            cap["server"]["error"] = cap["phone"]["error"] = "Error: net::ERR_NAME_NOT_RESOLVED"
        return cap
    feed = lambda seen: phishfeed.fetch(client=lists_client(), limit=10, seen=seen)  # noqa: E731
    client = make_client(phish_feed=feed, capture=capture)
    run = client.post("/api/watch/run").json()
    lists = run["public_lists"]
    assert lists["status"] == "done" and lists["read"] == 5 and lists["dead"] == 1
    assert lists["red"] >= 1 and set(lists["cases"]) <= set(run["cases"])
    open_ = client.get("/api/cases", params={"status": "open", "reveal": True}).json()
    from_lists = [c for c in open_ if c["source"] == "publiclist/openphish"]
    assert from_lists and all(c["verdict"] == "red" for c in from_lists)
    assert not any("dead-link" in c["link"] for c in open_)
    # a red case from the list can be sealed, approved and gets a takedown pack
    cid = from_lists[0]["id"]
    assert client.post(f"/api/cases/{cid}/seal").status_code == 200
    assert client.post(f"/api/cases/{cid}/approve", json={"method": "click"}).status_code == 200
    assert client.get(f"/api/cases/{cid}/takedown").status_code == 200
    # the known-bad reason credits the list
    case = client.get(f"/api/cases/{cid}", params={"reveal": True}).json()
    kb = [r for r in case["verdict_full"]["reasons"] if r["code"] == "known_bad"]
    assert kb and "OpenPhish" in kb[0]["evidence"]["source"]
    steps = client.get(f"/api/watch/runs/{run['run_id']}/replay", params={"reveal": True}).json()["steps"]
    assert any(s["action"] == "dead" and "dead-link" in s["detail"]["link"] for s in steps)
    assert any(s["action"] == "ask" and s["detail"]["query"] == "public scam lists" for s in steps)


def test_grey_results_without_a_brand_reason_stay_in_the_round(make_client):
    plain = {"result": {"source": "brave", "kind": "organic", "link": "https://some-blog.example/post"},
             "verdict": {"link": "https://some-blog.example/post", "verdict": "grey", "is_fraud": False, "score": 0.6,
                         "reasons": [{"code": "new_domain", "ar": "x", "en": "y", "evidence": {}}],
                         "model_version": "m", "scored_at": "2026-11-25T00:00:00Z"},
             "suspicious": True, "topic": "fines"}

    def one(cost_sink):
        return {"id": "r1", "steps": [], "results": [plain]}
    run = make_client(watch_round=one).post("/api/watch/run").json()
    assert run["status"] == "done" and run["results"] == 1 and run["cases"] == []


def test_old_grey_cases_without_a_brand_reason_are_archived_not_deleted(make_client, tmp_path):
    client = make_client(db="old.db")
    store = client.app.state.store
    grey = {"link": "https://blog.example/", "verdict": "grey", "score": 0.6,
            "reasons": [{"code": "new_domain", "ar": "x", "en": "y"}]}
    branded = {**grey, "link": "https://tamm-pay.example/", "reasons": [{"code": "brand_mismatch", "ar": "x", "en": "y"}]}
    for v in (grey, branded):
        store.execute("INSERT INTO cases (link, source, verdict, score, verdict_json, opened_at) VALUES (?,?,?,?,?,?)",
                      (v["link"], "watch", "grey", 0.6, dumps(v), now_iso()))
    assert watchrun.archive_quiet_grey(store) == 1
    status = {r["link"]: r["status"] for r in store.all("SELECT link, status FROM cases")}
    assert status == {"https://blog.example/": "archived", "https://tamm-pay.example/": "open"}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def test_scale_answers_at_once_warming_then_cached_with_its_age(tmp_path):
    clock, calls = Clock(), []

    def count():
        calls.append(1)
        return {"status": "live", "new_domains": {"total": 5, "lookalikes": []}}
    cache = FeedCache(count, tmp_path / "feeds.json", every=3600, clock=clock)
    cache.refresh_soon = lambda: None  # nothing in the background in this test
    assert cache.get()["status"] == "warming" and calls == []  # never counts on the request
    cache.refresh()
    clock.t += 7 * 60
    got = cache.get()
    assert got["new_domains"]["total"] == 5 and got["updated_minutes_ago"] == 7 and got["updated_at"]
    # a restart answers at once with the last known numbers from the volume
    again = FeedCache(lambda: 1 / 0, tmp_path / "feeds.json", clock=clock)
    again.refresh_soon = lambda: None
    assert again.get()["new_domains"]["total"] == 5


def test_a_failed_count_keeps_the_last_numbers(tmp_path):
    clock = Clock()
    box = {"v": {"status": "live", "n": 1}}

    def count():
        if box["v"] is None:
            raise RuntimeError("feed down")
        return box["v"]
    cache = FeedCache(count, None, every=60, clock=clock)
    cache.refresh_soon = lambda: None
    cache.refresh()
    box["v"] = None
    clock.t += 120
    cache.refresh()
    assert cache.get()["n"] == 1


def test_the_scale_endpoint_and_voice_tool_say_how_old_the_numbers_are(make_client):
    client = make_client()
    for body in (client.get("/api/feeds").json(), client.post("/api/voice/tools/scale", json={}).json()):
        assert body["status"] == "live" and body["updated_minutes_ago"] == 0 and body["updated_at"]
