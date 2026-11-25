import inspect
import json

import istibaq.model.features as features
from istibaq.eval import gate, scorecard
from istibaq.eval.stats import wilson
from istibaq.model import FEATURE_NAMES, load


def test_forbidden_features_never_return():
    names = " ".join(FEATURE_NAMES).lower()
    for bad in features.FORBIDDEN_FEATURES:
        assert bad not in names, bad
    m = load()
    assert list(m.meta["features"]) == list(FEATURE_NAMES)


def test_scheme_www_and_trailing_slash_do_not_change_score():
    m = load()
    forms = ["example.com", "example.com/", "http://example.com", "https://www.example.com/", "HTTPS://WWW.EXAMPLE.COM"]
    s = m.predict_many(forms)
    assert max(s) - min(s) < 1e-9


def test_contract_load_and_version_names_cut_date():
    m = load()
    assert m is not None and m.cut_date in m.version
    p = m.predict("adpolice-fines-pay.test/login")
    assert 0.0 <= p <= 1.0


def test_lookalike_scores_above_real():
    m = load()
    assert m.predict("tamm.abudhabi") < 0.5
    assert m.predict("http://tamm-abudhabi-fines-pay.test/verify/login") > m.predict("tamm.abudhabi")


def test_sealed_testset_hash_matches_manifest():
    rows, manifest = scorecard.load_testset(verify=True)
    assert len(rows) == manifest["rows"]
    assert all(not r["counted"] for r in rows if r["slice"].startswith("stress"))


def test_scorecard_has_ranges():
    card = scorecard.load()
    for d in card["slices"].values():
        lo, hi = d["range95"]
        assert lo <= d["rate"] <= hi


def test_wilson():
    lo, hi = wilson(0, 308)
    assert lo < 1e-9 and 0.01 < hi < 0.013


def test_gate_sample_passes_and_detects_regression(tmp_path):
    assert gate.main(["--baseline", str(gate.BASELINE)]) == 0
    base = json.loads(gate.BASELINE.read_text())
    p = tmp_path / "b.json"
    for key, val in (("fresh_catch_openphish", 1.01), ("model_version", "other"),
                     ("scored_with", "other"), ("sweep_size", 1)):
        b = dict(base, **{key: val})
        p.write_text(json.dumps(b))
        assert gate.main(["--baseline", str(p)]) == 1, key


def test_gate_fails_when_sweep_size_differs():
    assert gate.main(["--limit", "100", "--baseline", str(gate.BASELINE)]) == 1


def test_sweep_is_above_training_cutoff():
    m = load()
    assert m.meta["tranco_rank_cutoff"] < 200_000


def test_path_on_real_domain_moves_score_little():
    m = load()
    for d in ("alrostamani.ae", "example.com", "wikipedia.org", "noon.com"):
        bare = m.predict(f"https://{d}")
        deep = m.predict(f"https://{d}/en/support/customer-service/update-account/login/verify")
        assert abs(deep - bare) < 0.1, (d, bare, deep)


def test_backslash_and_userinfo_parse_to_real_host():
    for link in ("https://evil.test\\@adpolice.gov.ae/login", "https://evil.test\\.adpolice.gov.ae",
                 "https://adpolice.gov.ae@evil.test/login"):
        p = features.parse(link)
        assert p.host == "evil.test", (link, p.host)
