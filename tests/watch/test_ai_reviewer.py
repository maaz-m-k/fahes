"""The live AI second opinion: frozen policy, band only, daily cap, and silent fallback to pure code."""
import json

import httpx
import pytest

from istibaq.adapters.second_opinion import OpinionCache, Reviewer, frozen_policy
from istibaq.core.scorer import score_many

IN_BAND = "fines-portal.example"      # grey, score ~0.79: inside the frozen band
GREEN = "https://www.tamm.abudhabi/"
OUT_OF_BAND = "x7k2.pages.dev"        # score ~1.0: above the band


def model(log, verdict="fake", cost=0.001):
    def handler(request):
        sent = json.loads(json.loads(request.content)["messages"][1]["content"])["links"]
        log.append([it["address"] for it in sent])
        items = [{"id": it["id"], "verdict": verdict, "confidence": 0.95, "brand": "", "brand_domain": "",
                  "why_en": "looks like a fines scam", "why_ar": "يشبه احتيال المخالفات"} for it in sent]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"items": items})}}],
                                         "usage": {"cost": cost}})
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-SECRET")


def test_frozen_policy_is_the_measured_one():
    model_id, pol = frozen_policy()
    assert model_id == "google/gemini-2.5-flash-lite"
    assert pol.idea == "second_opinion" and pol.conf == 0.8 and pol.lo == 0.7 and pol.hi == 0.99


def test_only_links_in_the_band_are_sent_and_the_verdict_changes(key, tmp_path):
    log, costs = [], []
    r = Reviewer(client=model(log), cost_sink=lambda s, a, d: costs.append(a), cache=OpinionCache(tmp_path / "c.jsonl"))
    links = [IN_BAND, GREEN, OUT_OF_BAND]
    before = score_many(links)
    after = r.review(before, "judging")
    assert log == [[IN_BAND]]
    assert not before[0].is_fraud and after[0].is_fraud
    assert "ai_second_opinion" in {x.code for x in after[0].reasons}
    assert after[1] == before[1] and after[2] == before[2]
    assert costs == [0.001]


def test_officer_setting_is_never_sent(key, tmp_path):
    log = []
    r = Reviewer(client=model(log), cache=OpinionCache(tmp_path / "c.jsonl"))
    vs = score_many([IN_BAND], mode="officer")
    assert r.review(vs, "officer") == vs and log == []


def test_no_key_means_pure_code_silently(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    log = []
    vs = score_many([IN_BAND])
    assert Reviewer(client=model(log), cache=OpinionCache(tmp_path / "c.jsonl")).review(vs, "judging") == vs
    assert log == []


def test_daily_cap_reached_means_pure_code_silently(key, tmp_path):
    log = []
    r = Reviewer(client=model(log), cache=OpinionCache(tmp_path / "c.jsonl"), max_usd_per_day=1.0,
                 spent_today=lambda: 1.0)
    vs = score_many([IN_BAND])
    assert r.review(vs, "judging") == vs and log == []


def test_model_outage_means_pure_code_silently(key, tmp_path):
    def boom(request):
        return httpx.Response(503)
    r = Reviewer(client=httpx.Client(transport=httpx.MockTransport(boom)), cache=OpinionCache(tmp_path / "c.jsonl"))
    vs = score_many([IN_BAND])
    assert r.review(vs, "judging") == vs


def test_cached_answer_is_reused_without_a_call(key, tmp_path):
    cache = OpinionCache(tmp_path / "c.jsonl")
    Reviewer(client=model([]), cache=cache).review(score_many([IN_BAND]), "judging")
    log = []
    out = Reviewer(client=model(log), cache=OpinionCache(tmp_path / "c.jsonl")).review(score_many([IN_BAND]), "judging")
    assert log == [] and out[0].is_fraud


def test_cli_ai_flag_without_a_key_still_scores_offline(monkeypatch, tmp_path, capsys):
    from istibaq.cli import main
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    f = tmp_path / "links.txt"
    f.write_text(IN_BAND + "\n")
    assert main(["score", str(f), "--ai"]) == 0
    out = capsys.readouterr()
    assert "no" in out.out.splitlines()[1] and "OPENROUTER_API_KEY" in out.err


def test_cli_ai_flag_uses_the_second_opinion(key, monkeypatch, tmp_path, capsys):
    from istibaq import cli
    log = []
    monkeypatch.setattr(cli, "_reviewer", lambda: Reviewer(client=model(log), cache=OpinionCache(tmp_path / "c.jsonl")))
    f = tmp_path / "links.txt"
    f.write_text(IN_BAND + "\n")
    assert cli.main(["score", str(f), "--ai"]) == 0
    assert "ai_second_opinion" in capsys.readouterr().out and log == [[IN_BAND]]


def test_default_cli_never_calls_a_model(key, monkeypatch, tmp_path, capsys):
    from istibaq import cli
    monkeypatch.setattr(cli, "_reviewer", lambda: pytest.fail("the default command must not build the AI reviewer"))
    f = tmp_path / "links.txt"
    f.write_text(IN_BAND + "\n")
    assert cli.main(["score", str(f)]) == 0
