import pytest

from istibaq.adapters import BraveSearch, CTReader, NewDomains, PlacesSearch, RDAP
from istibaq.adapters.dataforseo import GoogleSearch, Ledger
from istibaq.adapters.contract import OnlineFacts
from istibaq.adapters.recorded import recorded_client
from istibaq.store.db import Store
from istibaq.feeds import certificate_count, detect_drill, new_domain_count
from istibaq.watch import QUESTIONS, run_round, show_work


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for k in ("BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"):
        monkeypatch.setenv(k, "test-key")
    monkeypatch.setenv("ISTIBAQ_DATAFORSEO", "1")


@pytest.fixture
def google(tmp_path):
    """Google results and ads through the DataForSEO recorded fake (never the real service)."""
    def make(client, sink=lambda *a: None):
        return GoogleSearch(Ledger(Store(str(tmp_path / "g.db"))), client=client, cost_sink=sink, sleep=lambda s: None)
    return make


def test_questions_cover_topics_in_both_languages():
    assert {q.topic for q in QUESTIONS} == {"fines", "bills", "helplines", "banks", "government"}
    assert {q.lang for q in QUESTIONS} == {"ar", "en"}


def test_round_scores_results_and_flags_suspects(google):
    c, costs = recorded_client(), []
    s = lambda *a: costs.append(a)
    rnd = run_round([google(c, s), BraveSearch(c, s)], maps=PlacesSearch(c, s), questions=QUESTIONS[:2] + QUESTIONS[8:9])
    links = {r.result.link: r for r in rnd.results}
    assert links["https://www.tamm.abudhabi/en/aspects-of-life/transport/fines"].verdict.verdict == "green"
    assert not links["https://www.adpolice.gov.ae/en/services/traffic-fines"].suspicious
    sus = {r.result.link for r in rnd.suspicious}
    assert "https://adpolice-fines-pay.example/discount" in sus      # sponsored ad
    assert "https://tamm-abudhabi-pay.test/login" in sus             # organic look-alike
    maps = links["http://fines-center-ad.example/"]
    assert maps.result.kind == "maps" and maps.verdict.verdict in {"grey", "red"}
    assert maps.suspicious == bool(maps.verdict.reasons or maps.verdict.verdict == "red")
    assert any(r.result.kind == "maps" for r in rnd.results)
    actions = [st.action for st in rnd.steps]
    assert "ask" in actions and "flag" in actions and rnd.finished_at
    d = rnd.to_dict()
    assert d["suspicious"] and all("time" in st for st in d["steps"])
    assert costs  # every paid call recorded


def test_round_skips_services_without_keys(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY")
    rnd = run_round([BraveSearch(recorded_client())], questions=QUESTIONS[:1])
    assert rnd.steps[0].action == "skip" and rnd.results == []


def test_online_facts_feed_the_scorer(google):
    rdap = RDAP(recorded_client())
    rnd = run_round([google(recorded_client())], questions=QUESTIONS[:1],
                    online_for=lambda link: OnlineFacts(rdap_age_days=rdap.age_days("tamm-abudhabi-pay.test")))
    r = next(r for r in rnd.results if "tamm-abudhabi-pay" in r.result.link)
    assert any(x.code == "new_domain" and x.online for x in r.verdict.reasons)


def test_visible_mode_opens_only_green_pages(google):
    rnd = run_round([google(recorded_client())], questions=QUESTIONS[:1])
    opened = []
    show_work(rnd, opened.append)
    assert opened and all(".gov.ae" in u or "tamm.abudhabi" in u for u in opened)


def test_feeds_are_labelled_and_narrowed_to_lookalikes():
    certs = certificate_count(CTReader(recorded_client()))
    assert certs.label == "live" and certs.rate_per_hour == 45000.0 and "Argon" in certs.source
    assert {h["name"] for h in certs.lookalikes} == {"tamm-abudhabi-pay.test", "www.tamm-abudhabi-pay.test"}
    nrd = new_domain_count(NewDomains(recorded_client()))
    assert nrd.label == "borrowed" and nrd.total == 5
    assert {h["name"] for h in nrd.lookalikes} == {"adpolice-fines-pay.example", "tamm-abudhabi-pay.test",
                                                   "emiratesnbd-secure.test"}


def test_drill_detection():
    d = detect_drill("drill.istibaq.example", "2026-11-24T22:40:00Z", CTReader(recorded_client()))
    assert d.found_at == "2026-11-24T23:10:05Z" and d.minutes_to_find == 30.1 and "crt.sh" in d.feed
    missing = detect_drill("drill.istibaq.example", "2026-11-25T01:00:00Z", CTReader(recorded_client()))
    assert missing.found_at is None


def test_maps_listing_with_official_name_and_wrong_phone_is_suspicious(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    c = recorded_client()
    rnd = run_round([], maps=PlacesSearch(c), questions=[q for q in QUESTIONS if q.maps][:1])
    by_title = {r.result.title: r for r in rnd.results}
    fake = by_title["Abu Dhabi Police Fines Help Desk"]
    assert fake.suspicious and "listing_phone_not_official" in {x.code for x in fake.verdict.reasons}
    assert by_title["Abu Dhabi Police GHQ"].verdict.verdict == "green"
    assert not by_title["Some cafe"].suspicious
