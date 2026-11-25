"""AI second opinion on uncertain links: what it may and may never change (reserved names for invented fakes)."""
import pytest

from istibaq.core import second_opinion as so
from istibaq.core.scorer import score


def op(verdict, confidence=0.95, brand="", brand_domain=""):
    return so.Opinion(verdict=verdict, confidence=confidence, brand=brand, brand_domain=brand_domain,
                      why_en="because", why_ar="لأن", model="fake-model")


SECOND = so.Policy(idea="second_opinion", conf=0.8, lo=0.5, hi=1.0)


def codes(v):
    return {r.code for r in v.reasons}


# ---------- never touched ----------

@pytest.mark.parametrize("link", ["https://www.tamm.abudhabi/fines", "adpolice.gov.ae", "u.ae/en"])
def test_register_green_is_never_sent_and_never_changed(link):
    v = score(link)
    assert v.verdict == "green"
    assert not so.eligible(v)
    for pol in (SECOND, so.Policy(idea="brand_reading"), so.Policy(idea="builder_clear")):
        out = so.apply(v, op("fake", 1.0, brand="TAMM"), pol, "judging")
        assert out.verdict == "green" and not out.is_fraud and out.score == v.score


def test_popular_site_is_not_sent():
    v = score("google.com")
    assert not so.eligible(v)


def test_red_is_never_cleared():
    v = score("evil.test\\@adpolice.gov.ae")
    assert v.verdict == "red"
    out = so.apply(v, op("real", 1.0), SECOND, "judging")
    assert out.verdict == "red" and out.is_fraud


def test_no_opinion_changes_nothing():
    v = score("x7k2.pages.dev")
    assert so.apply(v, None, SECOND, "judging") == v


# ---------- idea 1: second opinion inside the band ----------

def test_confident_fake_raises_a_grey_link_in_the_band():
    v = score("mybakery.example")
    assert v.verdict == "grey"
    pol = so.Policy(idea="second_opinion", conf=0.8, lo=0.0, hi=1.0)
    out = so.apply(v, op("fake", 0.9), pol, "judging")
    assert out.is_fraud and out.score >= 0.9
    assert "ai_second_opinion" in codes(out)
    assert out.verdict == "grey"  # the AI is never an independent reason: it never makes red


def test_confident_real_clears_a_flagged_grey_link():
    v = score("x7k2.pages.dev")
    assert v.verdict == "grey" and v.is_fraud
    out = so.apply(v, op("real", 0.9), SECOND, "judging")
    assert not out.is_fraud and out.score < 0.9
    assert "ai_second_opinion" in codes(out)


def test_low_confidence_or_unsure_changes_nothing():
    v = score("x7k2.pages.dev")
    assert so.apply(v, op("real", 0.5), SECOND, "judging").is_fraud
    assert so.apply(v, op("unsure", 0.99), SECOND, "judging").is_fraud


def test_outside_the_band_changes_nothing():
    v = score("x7k2.pages.dev")
    pol = so.Policy(idea="second_opinion", conf=0.8, lo=0.0, hi=0.2)
    assert so.apply(v, op("real", 0.99), pol, "judging").is_fraud


def test_second_opinion_never_changes_the_officer_setting():
    v = score("x7k2.pages.dev", mode="officer")
    out = so.apply(v, op("fake", 1.0), so.Policy(idea="second_opinion", conf=0.5, lo=0.0, hi=1.0), "officer")
    assert out.is_fraud == v.is_fraud and out.verdict == v.verdict


def test_raise_only_policy_never_clears():
    v = score("x7k2.pages.dev")
    pol = so.Policy(idea="second_opinion", conf=0.8, lo=0.0, hi=1.0, clear=False)
    assert so.apply(v, op("real", 1.0), pol, "judging").is_fraud


# ---------- idea 2: brand reading, the register decides ----------

def test_brand_named_by_the_ai_on_an_address_that_is_not_its_own_adds_a_brand_reason():
    v = score("fines-centre.example", mode="officer")
    assert "brand_mismatch" not in codes(v)
    out = so.apply(v, op("fake", 0.9, brand="Abu Dhabi Police"), so.Policy(idea="brand_reading"), "officer")
    assert "ai_brand_mismatch" in codes(out)
    assert out.score > v.score
    r = next(r for r in out.reasons if r.code == "ai_brand_mismatch")
    assert r.evidence["family"] == "abu_dhabi_police" and r.ar and r.en


def test_brand_reading_is_ignored_for_a_brand_outside_the_register():
    v = score("fines-centre.example")
    out = so.apply(v, op("fake", 0.9, brand="Some Unknown Shop"), so.Policy(idea="brand_reading"), "judging")
    assert out == v


def test_brand_reading_never_accuses_the_brands_own_domain():
    # a licensed global brand domain: owned, not accused
    v = score("https://support.apple.com/x")
    out = so.apply(v, op("fake", 0.9, brand="Apple"), so.Policy(idea="brand_reading"), "judging")
    assert "ai_brand_mismatch" not in codes(out)


def test_brand_reading_does_not_double_count_a_brand_the_register_already_found():
    v = score("adpolice-pay.test")
    assert "brand_mismatch" in codes(v)
    out = so.apply(v, op("fake", 0.9, brand="Abu Dhabi Police"), so.Policy(idea="brand_reading"), "judging")
    assert out.score == v.score


def test_global_brand_reading_needs_the_brand_in_the_address_and_a_popular_brand_domain():
    v = score("coinbase-verify.example")
    pol = so.Policy(idea="brand_reading_global")
    out = so.apply(v, op("fake", 0.9, brand="Coinbase", brand_domain="coinbase.com"), pol, "judging")
    assert "ai_brand_mismatch" in codes(out)
    # brand name not written in the address: no accusation
    w = score("crypto-verify.example")
    assert so.apply(w, op("fake", 0.9, brand="Coinbase", brand_domain="coinbase.com"), pol, "judging") == w
    # the brand's claimed domain is not a known popular site: no accusation
    assert so.apply(v, op("fake", 0.9, brand="Coinbase", brand_domain="coinbase-real.test"), pol, "judging") == v
    # the address is on the brand's own domain
    own = score("https://pro.coinbase.com/x")
    assert "ai_brand_mismatch" not in codes(so.apply(own, op("fake", 0.9, brand="Coinbase", brand_domain="coinbase.com"), pol, "judging"))


# ---------- idea 3: free-builder pages only ----------

def test_builder_clear_only_touches_free_builder_pages():
    pol = so.Policy(idea="builder_clear", conf=0.8)
    v = score("x7k2.pages.dev")
    assert not so.apply(v, op("real", 0.9), pol, "judging").is_fraud
    w = score("crypto-verify.example")
    assert w.is_fraud and w.verdict == "grey"
    assert so.apply(w, op("real", 0.9), pol, "judging").is_fraud
    assert so.apply(v, op("fake", 0.99), pol, "judging").is_fraud == v.is_fraud


# ---------- what the model is told ----------

def test_facts_carry_the_checkers_reasons_but_never_its_score():
    v = score("x7k2.pages.dev")
    f = so.facts(v)
    assert f["address"] == "x7k2.pages.dev"
    assert f["free_builder"] == "pages.dev"
    assert "free_host" in f["checker_reasons"]
    assert "score" not in f and "is_fraud" not in f


def test_brand_reading_can_be_limited_to_the_officer_setting():
    pol = so.Policy(idea="brand_reading_global", officer_only=True)
    o = op("fake", 0.9, brand="Coinbase", brand_domain="coinbase.com")
    v = score("coinbase-verify.example")
    assert so.apply(v, o, pol, "judging") == v
    w = score("coinbase-verify.example", mode="officer")
    assert "ai_brand_mismatch" in codes(so.apply(w, o, pol, "officer"))


def test_brand_reading_can_require_a_confident_fake_verdict():
    pol = so.Policy(idea="brand_reading_global", conf=0.8, require_fake=True)
    v = score("coinbase-verify.example")
    assert so.apply(v, op("real", 0.9, brand="Coinbase", brand_domain="coinbase.com"), pol, "judging") == v
    assert so.apply(v, op("fake", 0.5, brand="Coinbase", brand_domain="coinbase.com"), pol, "judging") == v
    assert "ai_brand_mismatch" in codes(
        so.apply(v, op("fake", 0.9, brand="Coinbase", brand_domain="coinbase.com"), pol, "judging"))
