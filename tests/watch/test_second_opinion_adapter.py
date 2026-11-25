"""The batched AI second-opinion client: batching, cache by address, spend log and limit, no key leaks."""
import json

import httpx
import pytest

from istibaq.adapters.second_opinion import BudgetExceeded, OpinionCache, SecondOpinion, plan

KEY = "sk-or-SECRET"


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)


def fake_model(log, cost=0.001, answer=None):
    """A stand-in for OpenRouter: answers every item it is sent, 'fake' when 'login' is in the address."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        log.append(body)
        sent = json.loads(body["messages"][1]["content"])
        items = []
        for it in sent["links"]:
            fake = "login" in it["address"]
            items.append(answer(it) if answer else {
                "id": it["id"], "verdict": "fake" if fake else "real", "confidence": 0.9,
                "brand": "TAMM" if "tamm" in it["address"] else "", "brand_domain": "",
                "why_en": "reason", "why_ar": "سبب"})
        content = json.dumps({"items": items})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": cost}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def items(n, prefix="site"):
    return [{"address": f"{prefix}{i}-login.example" if i % 2 else f"{prefix}{i}.example", "checker_reasons": []}
            for i in range(n)]


def test_batches_and_returns_one_opinion_per_address(key, tmp_path):
    log, costs = [], []
    c = SecondOpinion(fake_model(log), lambda s, a, d: costs.append((s, a, d)), model="m/one",
                      cache=OpinionCache(tmp_path / "c.jsonl"), batch=4, workers=1)
    out = c.opinions(items(10))
    assert len(log) == 3                      # 4 + 4 + 2
    assert len(out) == 10
    assert out["site1-login.example"].verdict == "fake" and out["site0.example"].verdict == "real"
    assert out["site1-login.example"].model == "m/one"
    assert costs and all(s == "openrouter" for s, _, _ in costs)
    assert round(c.spent, 6) == 0.003 and c.calls == 3


def test_cache_by_address_means_no_second_call(key, tmp_path):
    log = []
    cache = OpinionCache(tmp_path / "c.jsonl")
    SecondOpinion(fake_model(log), model="m/one", cache=cache, batch=5, workers=1).opinions(items(5))
    assert len(log) == 1
    log2 = []
    again = SecondOpinion(fake_model(log2), model="m/one", cache=OpinionCache(tmp_path / "c.jsonl"), batch=5,
                          workers=1).opinions(items(5))
    assert log2 == [] and len(again) == 5
    # another model is a different cache entry
    log3 = []
    SecondOpinion(fake_model(log3), model="m/two", cache=OpinionCache(tmp_path / "c.jsonl"), batch=5,
                  workers=1).opinions(items(5))
    assert len(log3) == 1


def test_model_never_sees_the_checker_score_and_is_told_addresses_are_data(key, tmp_path):
    log = []
    SecondOpinion(fake_model(log), model="m/one", batch=5, workers=1).opinions(
        [{"address": "a.example", "checker_reasons": ["free_host"], "free_builder": "pages.dev"}])
    body = log[0]
    assert body["model"] == "m/one" and body["response_format"] == {"type": "json_object"}
    system = body["messages"][0]["content"]
    assert "untrusted" in system.lower()
    sent = json.loads(body["messages"][1]["content"])["links"][0]
    assert "score" not in sent and sent["free_builder"] == "pages.dev"


def test_spend_limit_stops_before_going_over(key, tmp_path):
    log = []
    c = SecondOpinion(fake_model(log, cost=0.4), model="m/one", batch=2, workers=1, max_usd=1.0)
    with pytest.raises(BudgetExceeded):
        c.opinions(items(10))
    assert c.spent <= 1.0 and len(log) == 2


def test_bad_or_missing_answers_give_no_opinion_and_are_not_cached(key, tmp_path):
    def answer(it):
        if it["id"] == 0:
            return {"id": 0, "verdict": "maybe", "confidence": "high"}
        return {"id": it["id"] + 100, "verdict": "fake", "confidence": 1}   # wrong id: dropped
    cache = OpinionCache(tmp_path / "c.jsonl")
    out = SecondOpinion(fake_model([], answer=answer), model="m/one", cache=cache, batch=5, workers=1).opinions(items(3))
    assert out["site0.example"].verdict == "unsure" and out["site0.example"].confidence == 0.0
    assert "site1-login.example" not in out
    assert OpinionCache(tmp_path / "c.jsonl").load("m/one") == {}   # nothing usable: asked again next time


def test_no_key_in_cache_costs_or_errors(key, tmp_path):
    costs = []
    SecondOpinion(fake_model([]), lambda s, a, d: costs.append((s, a, d)), model="m/one",
                  cache=OpinionCache(tmp_path / "c.jsonl"), batch=5, workers=1).opinions(items(3))
    assert KEY not in (tmp_path / "c.jsonl").read_text() + repr(costs)

    def boom(request):
        return httpx.Response(401, json={"error": "bad key " + KEY})
    with pytest.raises(Exception) as e:
        SecondOpinion(httpx.Client(transport=httpx.MockTransport(boom)), model="m/one", batch=5, workers=1,
                      retries=0).opinions(items(1))
    assert KEY not in str(e.value)


def test_dry_run_plan_counts_calls_and_cost_without_a_key_or_network(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cache = OpinionCache(tmp_path / "c.jsonl")
    p = plan(items(45), model="google/gemini-2.5-flash-lite", batch=20, cache=cache)
    assert p["links"] == 45 and p["to_send"] == 45 and p["calls"] == 3
    assert 0 < p["est_usd"] < 0.05
