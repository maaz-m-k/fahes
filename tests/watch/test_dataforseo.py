"""DataForSEO (Google results and sponsored ads): every spend limit is enforced in code.

The account holds $1 for the whole hackathon, so these tests never reach DataForSEO.
They drive the adapter through a fake built from the documented response shapes in
tests/fixtures/recorded/dataforseo_*.json (reserved names only).
"""
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from istibaq.adapters import dataforseo as dfs
from istibaq.adapters.base import AdapterError, MissingKey
from istibaq.adapters.recorded import recorded_client
from istibaq.store.db import Store
from istibaq.watch import QUESTIONS

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
FINES = "pay abu dhabi police traffic fine"
TASK_ID = "11250000-0000-0000-0000-000000000001"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeDataForSEO:
    """Answers like DataForSEO's documented endpoints and counts every call by kind."""

    def __init__(self, balance=0.9, ready_after=0):
        self.balance = balance
        self.ready_after = ready_after   # number of tasks_ready polls before the task shows up
        self.calls: list[str] = []
        self.posted: list[list[dict]] = []
        self.auth: set[str] = set()

    @property
    def paid(self):
        return self.calls.count("task_post")

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.dataforseo.com"
        self.auth.add(request.headers.get("authorization", ""))
        path = request.url.path
        if path == "/v3/appendix/user_data":
            self.calls.append("user_data")
            body = load("dataforseo_user_data.json")
            body["tasks"][0]["result"][0]["money"]["balance"] = self.balance
            return httpx.Response(200, json=body)
        if path == "/v3/serp/google/organic/task_post":
            self.calls.append("task_post")
            self.posted.append(json.loads(request.content))
            self.balance = round(self.balance - 0.0006, 6)
            return httpx.Response(200, json=load("dataforseo_task_post.json"))
        if path == "/v3/serp/google/organic/tasks_ready":
            self.calls.append("tasks_ready")
            body = load("dataforseo_tasks_ready.json")
            if self.ready_after > 0:
                self.ready_after -= 1
                body["tasks"][0]["result"] = []
                body["tasks"][0]["result_count"] = 0
            return httpx.Response(200, json=body)
        if path == f"/v3/serp/google/organic/task_get/advanced/{TASK_ID}":
            self.calls.append("task_get")
            return httpx.Response(200, json=load("dataforseo_task_get_advanced.json"))
        return httpx.Response(404, json={"status_code": 40400, "status_message": "Not Found."})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


class Clock:
    def __init__(self, at=datetime(2026, 11, 25, 8, 0, tzinfo=UTC)):
        self.at = at

    def __call__(self):
        return self.at

    def advance(self, **kw):
        self.at += timedelta(**kw)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("ISTIBAQ_DATAFORSEO", "1")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "team@istibaq.example")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "dfs-SECRET-password")


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


@pytest.fixture
def costs():
    return []


@pytest.fixture
def clock():
    return Clock()


def make(store, fake, costs, clock, **kw):
    sink = lambda service, amount, detail: costs.append((service, amount, detail))
    return dfs.GoogleSearch(dfs.Ledger(store), client=fake.client(), cost_sink=sink, clock=clock,
                            sleep=lambda s: None, **kw)


# ---------------------------------------------------------------- the switch and the five questions

def test_off_unless_switched_on(monkeypatch, store, costs, clock):
    monkeypatch.delenv("ISTIBAQ_DATAFORSEO", raising=False)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "x")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "y")
    fake = FakeDataForSEO()
    with pytest.raises(dfs.GoogleCheckOff):
        make(store, fake, costs, clock).search(FINES, "en")
    monkeypatch.setenv("ISTIBAQ_DATAFORSEO", "0")
    with pytest.raises(MissingKey):  # the round records a switched-off check as a skip
        make(store, fake, costs, clock).search(FINES, "en")
    assert fake.calls == [] and costs == []


def test_missing_credentials_cost_nothing(monkeypatch, on, store, costs, clock):
    monkeypatch.delenv("DATAFORSEO_PASSWORD")
    fake = FakeDataForSEO()
    with pytest.raises(MissingKey):
        make(store, fake, costs, clock).search(FINES, "en")
    assert fake.calls == [] and costs == []


def test_exactly_five_ad_prone_questions_are_marked():
    marked = [q for q in QUESTIONS if q.ad_prone]
    assert len(marked) == 5
    assert dfs.ad_prone_questions() == tuple(marked)
    texts = " ".join(q.text.lower() for q in marked)
    for word in ("fine", "bill", "customer care", "visa", "customer service number"):
        assert word in texts


def test_refuses_any_other_question(on, store, costs, clock):
    fake = FakeDataForSEO()
    with pytest.raises(dfs.NotAdProne):
        make(store, fake, costs, clock).search("TAMM login", "en")
    with pytest.raises(dfs.NotAdProne):  # right words, wrong language
        make(store, fake, costs, clock).search(FINES, "ar")
    assert fake.calls == [] and costs == []


# ---------------------------------------------------------------- one paid search

def test_paid_search_uses_the_standard_queue_and_returns_ads_and_organic(on, store, costs, clock):
    fake = FakeDataForSEO()
    res = make(store, fake, costs, clock).search(FINES, "en")
    assert fake.calls == ["user_data", "task_post", "tasks_ready", "task_get", "user_data"]
    task = fake.posted[0]
    assert task == [{"keyword": FINES, "location_code": 2784, "language_code": "en", "device": "desktop",
                     "os": "windows", "depth": 10, "priority": 1, "tag": "istibaq"}]
    expected = "Basic " + base64.b64encode(b"team@istibaq.example:dfs-SECRET-password").decode()
    assert fake.auth == {expected}

    ad = res[0]
    assert (ad.source, ad.kind, ad.label) == ("google_ad", "ad", "borrowed")
    assert ad.link == "https://adpolice-fines-pay.example/discount" and ad.title.startswith("Pay Your")
    assert ad.snippet.startswith("Settle")
    organic = [r for r in res if r.kind == "organic"]
    assert [r.source for r in organic] == ["google"] * 3
    assert [r.position for r in organic] == [1, 2, 3]
    assert "https://tamm-abudhabi-pay.test/login" in {r.link for r in organic}


def test_every_paid_search_is_logged_with_the_balance(on, store, costs, clock):
    make(store, FakeDataForSEO(balance=0.9), costs, clock).search(FINES, "en")
    assert len(costs) == 1
    service, amount, detail = costs[0]
    assert (service, amount) == ("dataforseo", 0.0006)
    assert detail["query"] == FINES and detail["lang"] == "en" and detail["task_id"] == TASK_ID
    assert detail["balance_before"] == 0.9 and detail["balance_after"] == 0.8994
    row = dfs.Ledger(store).status(clock())
    assert row["paid_today"] == 1 and row["last_balance"] == 0.8994


def test_no_key_ever_appears_in_results_or_costs(on, store, costs, clock):
    out = repr(make(store, FakeDataForSEO(), costs, clock).search(FINES, "en")) + repr(costs)
    out += repr(dfs.Ledger(store).status(clock()))
    assert "dfs-SECRET-password" not in out


# ---------------------------------------------------------------- the 6-hour cache

def test_same_question_within_six_hours_is_free(on, store, costs, clock):
    fake = FakeDataForSEO()
    g = make(store, fake, costs, clock)
    first = g.search(FINES, "en")
    clock.advance(hours=5, minutes=59)
    again = g.search(FINES, "en")
    assert [r.to_dict() for r in again] == [r.to_dict() for r in first]
    assert fake.paid == 1 and len(costs) == 1
    clock.advance(minutes=2)
    g.search(FINES, "en")
    assert fake.paid == 2 and len(costs) == 2


def test_the_cache_survives_a_restart(on, tmp_path, costs, clock):
    fake = FakeDataForSEO()
    make(Store(str(tmp_path / "x.db")), fake, costs, clock).search(FINES, "en")
    make(Store(str(tmp_path / "x.db")), fake, costs, clock).search(FINES, "en")
    assert fake.paid == 1


# ---------------------------------------------------------------- the balance reserve

def test_refuses_below_the_reserve_after_only_the_free_balance_call(on, store, costs, clock):
    fake = FakeDataForSEO(balance=0.2004)   # one more search would leave less than $0.20
    with pytest.raises(dfs.SpendRefused) as e:
        make(store, fake, costs, clock).search(FINES, "en")
    assert "reserve" in str(e.value)
    assert fake.calls == ["user_data"] and costs == []


def test_reserve_is_configurable(monkeypatch, on, store, costs, clock):
    monkeypatch.setenv("ISTIBAQ_DATAFORSEO_RESERVE_USD", "0.5")
    with pytest.raises(dfs.SpendRefused):
        make(store, FakeDataForSEO(balance=0.45), costs, clock).search(FINES, "en")
    fake = FakeDataForSEO(balance=0.45)
    make(store, fake, costs, clock, reserve_usd=0.1).search(FINES, "en")
    assert fake.paid == 1


def test_an_unreadable_balance_refuses(on, store, costs, clock):
    fake = FakeDataForSEO()
    fake.balance = None
    with pytest.raises(dfs.SpendRefused):
        make(store, fake, costs, clock).search(FINES, "en")
    assert fake.paid == 0


# ---------------------------------------------------------------- the daily cap (SQLite, not memory)

def test_daily_cap_is_persisted_and_resets_the_next_day(on, tmp_path, costs, clock):
    db = str(tmp_path / "cap.db")
    led = dfs.Ledger(Store(db))
    for i in range(dfs.DAILY_CAP):
        led.record_post(f"q{i}", "en", f"task-{i}", 0.0006, 0.9, clock())
    fake = FakeDataForSEO()
    with pytest.raises(dfs.SpendRefused) as e:
        make(Store(db), fake, costs, clock).search(FINES, "en")   # a fresh process sees the same count
    assert "30" in str(e.value)
    assert fake.calls == [] and costs == []
    clock.advance(days=1)
    make(Store(db), fake, costs, clock).search(FINES, "en")
    assert fake.paid == 1


def test_daily_cap_can_be_lowered_but_never_raised(monkeypatch, on, store, costs, clock):
    monkeypatch.setenv("ISTIBAQ_DATAFORSEO_DAILY_CAP", "500")
    assert dfs.daily_cap() == 30
    monkeypatch.setenv("ISTIBAQ_DATAFORSEO_DAILY_CAP", "0")
    fake = FakeDataForSEO()
    with pytest.raises(dfs.SpendRefused):
        make(store, fake, costs, clock).search(FINES, "en")
    assert fake.calls == []


# ---------------------------------------------------------------- a slow standard queue never pays twice

def test_a_queued_task_is_collected_later_without_a_second_charge(on, store, costs, clock):
    fake = FakeDataForSEO(ready_after=100)
    g = make(store, fake, costs, clock, wait_seconds=10, poll_every=5)
    with pytest.raises(dfs.StillQueued):
        g.search(FINES, "en")
    assert fake.paid == 1 and len(costs) == 1
    fake.ready_after = 0
    clock.advance(minutes=3)
    res = g.search(FINES, "en")
    assert res and fake.paid == 1 and len(costs) == 1
    assert dfs.Ledger(store).status(clock())["paid_today"] == 1


def test_a_failed_post_still_counts_against_the_cap_but_logs_no_cost(on, store, costs, clock):
    class Broken(FakeDataForSEO):
        def handler(self, request):
            if request.url.path.endswith("task_post"):
                self.calls.append("task_post")
                return httpx.Response(500, json={})
            return super().handler(request)
    fake = Broken()
    with pytest.raises(AdapterError):
        make(store, fake, costs, clock).search(FINES, "en")
    assert costs == []
    assert dfs.Ledger(store).status(clock())["paid_today"] == 1   # counted, to be safe


# ---------------------------------------------------------------- shared recorded fake

def test_recorded_client_replays_dataforseo(on, store, costs, clock):
    sink = lambda *a: costs.append(a)
    res = dfs.GoogleSearch(dfs.Ledger(store), client=recorded_client(), cost_sink=sink, clock=clock,
                           sleep=lambda s: None).search(FINES, "en")
    assert {r.source for r in res} == {"google", "google_ad", "google_ai"}
    assert costs[0][:2] == ("dataforseo", 0.0006)


# ---------------------------------------------------------------- shapes seen in the real sample

def test_ai_overview_cited_links_become_google_ai_results(on, store, costs, clock):
    res = make(store, FakeDataForSEO(), costs, clock).search(FINES, "en")
    ai = [r for r in res if r.source == "google_ai"]
    assert [r.link for r in ai] == ["https://www.tamm.abudhabi/en/fines", "https://fines-ad-gov.example/pay"]
    assert all(r.kind == "ai_cited" and r.label == "borrowed" for r in ai)
    assert ai[1].title.startswith("Pay Abu Dhabi fines") and ai[1].position == 2
    # a null organic description is an empty snippet; knowledge-graph items are not results
    assert all(isinstance(r.snippet, str) for r in res)
    assert {r.source for r in res} == {"google", "google_ad", "google_ai"} and len(res) == 6


def test_task_get_still_queued_codes_mean_wait_not_pay(on, store, costs, clock):
    class Queued(FakeDataForSEO):
        def handler(self, request):
            if "/task_get/advanced/" in request.url.path:
                self.calls.append("task_get")
                body = load("dataforseo_task_get_advanced.json")
                body["tasks"][0].update(status_code=40602, status_message="Task In Queue.", result=None)
                return httpx.Response(200, json=body)
            return super().handler(request)
    fake = Queued()
    g = make(store, fake, costs, clock)
    with pytest.raises(dfs.StillQueued):
        g.search(FINES, "en")
    with pytest.raises(dfs.StillQueued):
        g.search(FINES, "en")
    assert fake.paid == 1 and len(costs) == 1
