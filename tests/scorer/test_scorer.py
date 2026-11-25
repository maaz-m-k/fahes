"""Scorer behaviour through its public seam: ``score()`` and ``score_many()``."""
import pytest

from istibaq.core.contract import OnlineFacts, Reason
from istibaq.core import register
from istibaq.core.scorer import score, score_many

REAL_UAE = [
    "https://www.adpolice.gov.ae/ar/",
    "https://tamm.abudhabi/en/life-events",
    "tamm.abudhabi",
    "https://u.ae/en/information-and-services",
    "https://uaepass.ae/",
    "https://icp.gov.ae/",
    "https://smartservices.icp.gov.ae/echannels/web/client/default.html",
    "https://eservices.dot.gov.abudhabi/",
    "https://www.dot.abudhabi.ae/",
    "https://www.adcb.com/en/personal/",
    "https://www.bankfab.com/en-ae/personal",
    "https://www.emiratesnbd.com/en",
    "https://www.adib.ae/en/",
    "https://www.etisalat.ae/en/",
    "https://www.du.ae/",
    "https://www.dewa.gov.ae/en/consumer",
    "https://www.addc.ae/",
    "https://www.rta.ae/",
    "https://www.mohre.gov.ae/",
    "https://www.dubaipolice.gov.ae/",
]

POPULAR = ["google.com", "https://www.youtube.com/", "facebook.com/", "wikipedia.org", "microsoft.com",
           "apple.com", "amazon.com", "netflix.com", "instagram.com", "linkedin.com", "github.com"]

LOOKALIKES = [
    "tamm-pay.test",
    "adpolice-fines.example",
    "https://tamm-gov-pay.test/login",
    "uaepass-verify.example",
    "emiratesnbd-secure-login.test",
    "adcb-online-banking.example",
    "http://t\u0430mm.test/pay",     # Cyrillic a in tamm
    "http://xn--tmm-6cd.test/pay",   # same, as punycode
]


@pytest.mark.parametrize("link", REAL_UAE)
def test_real_uae_pages_are_green(link):
    v = score(link)
    assert v.verdict == "green" and v.is_fraud is False
    v = score(link, mode="officer")
    assert v.verdict == "green" and v.is_fraud is False


@pytest.mark.parametrize("link", POPULAR)
def test_popular_sites_not_flagged(link):
    for mode in ("judging", "officer"):
        v = score(link, mode=mode)
        assert v.verdict != "red" and v.is_fraud is False


@pytest.mark.parametrize("link", LOOKALIKES)
def test_invented_lookalikes_turn_red_with_two_reasons(link):
    v = score(link)
    assert v.verdict == "red", v.to_dict()
    assert v.is_fraud is True
    codes = {r.code for r in v.reasons}
    assert "brand_mismatch" in codes
    assert len(codes) >= 2
    for r in v.reasons:
        assert r.ar and r.en


def test_output_contract_fields():
    d = score("tamm-pay.test").to_dict()
    assert set(d) == {"link", "verdict", "is_fraud", "score", "reasons", "model_version", "scored_at"}
    assert 0.0 <= d["score"] <= 1.0
    assert d["model_version"]
    assert d["scored_at"].endswith("Z")
    r = d["reasons"][0]
    assert set(r) == {"code", "ar", "en", "evidence", "time", "online"}


def test_short_link_offline_is_grey_destination_unknown():
    v = score("https://bit.ly/3xYzAbc")
    assert v.verdict == "grey" and v.is_fraud is False
    assert any(r.code == "short_link" and "destination unknown" in r.en for r in v.reasons)


def test_short_link_with_redirect_chain_judges_every_hop():
    online = OnlineFacts(redirect_chain=["https://bit.ly/3xYzAbc", "https://tamm-fines-pay.test/login"])
    v = score("https://bit.ly/3xYzAbc", online=online)
    assert v.verdict == "red"
    codes = {r.code for r in v.reasons}
    assert "cross_domain_redirect" in codes and "brand_mismatch" in codes


def test_short_link_to_official_site_not_accused():
    online = OnlineFacts(redirect_chain=["https://bit.ly/abc", "https://tamm.abudhabi/en"])
    v = score("https://bit.ly/abc", online=online)
    assert v.verdict != "red" and not v.is_fraud


def test_free_host_says_address_alone_cannot_tell():
    v = score("https://my-shop.github.io/")
    assert v.verdict == "grey"
    assert any(r.code == "free_host" and "cannot tell real from fake" in r.en for r in v.reasons)


def test_free_host_subdomain_never_green_even_with_brand_name():
    v = score("https://tamm.github.io/")
    assert v.verdict != "green"


def test_dead_link_scored_from_address_alone():
    # Reserved names never resolve; scoring must still work without any network.
    v = score("http://adpolice-traffic-fines-pay.example/pay/now")
    assert v.verdict == "red" and v.is_fraud


def test_trailing_slash_scheme_and_www_do_not_change_the_score():
    a = score("tamm-pay.test").score
    for variant in ("http://tamm-pay.test/", "https://www.tamm-pay.test", "HTTPS://TAMM-PAY.TEST/"):
        assert score(variant).score == a


def test_officer_mode_is_stricter_than_judging():
    links = ["sp28ct11-vemkaro-biz-kuzrani.pages.dev", "secure-login-update-account.xyz", "tamm.example"]
    for link in links:
        if score(link, mode="officer").is_fraud:
            assert score(link, mode="judging").is_fraud
    # A single strong reason can flag for the judges' file but is never red on the desk.
    v = score("secure-login-verify-account-update.xyz", mode="officer")
    if v.verdict != "red":
        assert v.is_fraud is False


def test_red_always_has_two_independent_reasons():
    links = LOOKALIKES + ["http://1.2.3.4/login", "paypa1-secure.xyz", "random-shop.example"]
    for link in links:
        for mode in ("judging", "officer"):
            v = score(link, mode=mode)
            if v.verdict == "red":
                assert len({r.code for r in v.reasons}) >= 2


def test_online_facts_add_reasons():
    online = OnlineFacts(rdap_age_days=3, cert_first_seen="2026-11-20T00:00:00Z",
                         two_view_difference="server saw a blank page; phone saw a payment form",
                         human_check_wall=True)
    v = score("https://parking-portal.example/", online=online)
    codes = {r.code for r in v.reasons}
    assert {"new_domain", "two_view_difference", "human_check_wall"} <= codes
    assert all(r.online for r in v.reasons if r.code in {"new_domain", "two_view_difference"})
    assert v.verdict == "red"


def test_payee_not_in_register_is_a_reason():
    v = score("https://fines-portal.example/", online=OnlineFacts(payee="Quick Pay Trading LLC"))
    assert any(r.code == "payee_not_in_register" for r in v.reasons)
    v = score("https://fines-portal.example/", online=OnlineFacts(payee="Abu Dhabi Police"))
    assert not any(r.code == "payee_not_in_register" for r in v.reasons)


def test_live_page_brand_mismatch():
    v = score("https://service-center.example/", online=OnlineFacts(live_page_brand="TAMM"))
    assert any(r.code == "live_brand_mismatch" for r in v.reasons)


def test_ai_reason_only_adds_never_clears():
    ai = Reason("page_claims_police", "الصفحة تدّعي أنها للشرطة", "Page claims to be the police", {}, "2026-11-25T00:00:00Z", True)
    green = score("https://www.adpolice.gov.ae/", online=OnlineFacts(ai_reason=ai))
    assert green.verdict == "green"
    base = score("tamm-pay.test")
    with_ai = score("tamm-pay.test", online=OnlineFacts(ai_reason=ai))
    assert with_ai.score >= base.score and with_ai.verdict == "red"


def test_officer_mark_not_a_scam_feeds_the_register():
    link = "tamm-partner-services.example"
    try:
        assert score(link).verdict == "red"
        hit = register.apply_edit(link, "not_scam", source="officer:desk-1", note="checked by phone")
        assert hit.status == "licensed"
        v = score(link)
        assert v.verdict == "grey" and v.is_fraud is False
    finally:
        register.clear_edits()
        from istibaq.core import scorer
        scorer.clear_cache()


def test_register_lookup_contract():
    hit = register.lookup("https://www.adpolice.gov.ae/en/")
    assert hit.status == "official" and hit.family == "abu_dhabi_police" and hit.evidence["source"]
    assert register.lookup("tamm-pay.test").status == "unknown"
    assert register.lookup("adpolice.github.io").status == "unknown"


def test_score_many_matches_score():
    links = ["tamm.abudhabi", "tamm-pay.test", "bit.ly/x"]
    vs = score_many(links)
    assert [v.verdict for v in vs] == [score(l).verdict for l in links]


def test_no_forbidden_features_in_evidence():
    v = score("https://tamm-pay.test/a/very/long/path/that/goes/on/")
    for r in v.reasons:
        for k in r.evidence:
            assert k not in {"path_length", "scheme", "www", "trailing_slash", "rank"}


NEVER_GREEN = [
    "https://evil.test\\@adpolice.gov.ae/login",
    "https://evil.test\\.adpolice.gov.ae",
    "https://adpolice.gov.ae@evil.test/login",
    "https://tamm.abudhabi:443@evil.example/",
    "https://forms.office.com/r/abc",
    "https://onedrive.live.com/redir?x",
    "https://sway.office.com/x",
    "https://1drv.ms/u/s!abc",
    "https://adpolice.github.io/",
]


@pytest.mark.parametrize("link", NEVER_GREEN)
def test_never_green(link):
    assert score(link).verdict != "green"


def test_real_microsoft_login_not_accused():
    for mode in ("judging", "officer"):
        v = score("https://login.microsoftonline.com/", mode=mode)
        assert v.verdict != "red" and v.is_fraud is False


def test_global_brand_lookalike_still_red():
    v = score("microsoft-account-verify.test/login")
    assert v.verdict == "red" and any(r.code == "brand_mismatch" for r in v.reasons)


@pytest.mark.parametrize("link", ["https://google.github.io/styleguide/pyguide.html",
                                  "https://facebook.github.io/react-native/",
                                  "https://my-bakery.wixsite.com/home",
                                  "https://www.canva.com/design/DAF/view"])
def test_real_free_host_pages_stay_grey(link):
    for mode in ("judging", "officer"):
        assert score(link, mode=mode).verdict == "grey"
    assert score(link, mode="officer").is_fraud is False


def test_path_publishing_platform_not_on_allow_list():
    v = score("https://www.canva.com/design/DAF/view")
    assert not any(r.code == "popular_site" for r in v.reasons)


def test_ordinary_words_are_not_brand_typos():
    v = score("https://visa-apply.com/")
    assert not any(r.code == "brand_mismatch" for r in v.reasons)


def test_latin_accent_lookalike_caught():
    v = score("https://tämm.com/")
    assert any(r.code == "brand_mismatch" for r in v.reasons)
    v = score("https://xn--tmm-qla.com/")
    assert any(r.code == "brand_mismatch" for r in v.reasons)


def test_hosting_is_not_a_second_independent_reason(monkeypatch):
    from istibaq.core import scorer as S
    from istibaq.core import reasons as R

    # A model that scores everything as fraud: a free-host page must still not turn red on hosting alone.
    monkeypatch.setattr(S, "_model", lambda: type("M", (), {"version": "stub", "predict": lambda self, l: 0.9999})())
    monkeypatch.setattr(S, "model_version", lambda: "stub")
    S.clear_cache()
    try:
        v = S.score("https://my-shop.github.io/")
        assert v.verdict == "grey"
        assert v.is_fraud is True  # judging: not green and raw score >= 0.9, as issue #9 says
        assert S.score("https://my-shop.github.io/", mode="officer").is_fraud is False
        assert any(r.code == "free_host" and "cannot tell real from fake" in r.en for r in v.reasons)
    finally:
        S.clear_cache()


@pytest.mark.parametrize("link", ["https://adp0lice-gov.com/fines", "https://tamm-ae.xyz/services/pay",
                                  "https://dewa-bill-pay.net/", "https://fab-bank-update.com/verify"])
def test_brand_in_host_lookalikes_flagged(link):
    v = score(link)
    assert v.is_fraud is True and any(r.code == "brand_mismatch" for r in v.reasons)


def test_s3_bucket_not_licensed():
    v = score("https://dhl-delivery.s3.us-east-2.amazonaws.example/login.html".replace(".example", ".com"))
    assert not any(r.code == "register_licensed" for r in v.reasons)
    assert any(r.code == "free_host" for r in v.reasons)


def test_non_decomposing_homoglyphs_caught():
    for link in ["https://t\u0251mm-pay.com/", "https://a\u00f0cb-login.com/"]:
        assert any(r.code == "brand_mismatch" for r in score(link).reasons), link


def test_digit_for_letter_lookalike_flagged():
    # With the trained model this may be grey (one family); the judges' is_fraud must hold either way.
    v = score("etisa1at-billing.test")
    assert v.is_fraud is True
    assert any(r.code == "brand_mismatch" for r in v.reasons)


def test_plain_s3_asset_not_red_and_no_brand():
    for mode in ("judging", "officer"):
        v = score("https://my-company-assets.s3.amazonaws.com/logo.png", mode=mode)
        assert v.verdict != "red"
        assert not any(r.code == "brand_mismatch" for r in v.reasons)
        assert any(r.code == "free_host" for r in v.reasons)


def test_brand_on_platform_subdomain_still_caught():
    v = score("https://tamm-fines-pay.github.io/")
    assert any(r.code == "brand_mismatch" for r in v.reasons)


def test_cyrillic_be_lookalike():
    assert any(r.code == "brand_mismatch" for r in score("https://adc\u0431.com/").reasons)


@pytest.mark.parametrize("link", ["https://tamm.abudhabi@evil.example/",
                                  "https://adpolice.gov.ae:443@evil.example/login"])
def test_official_name_before_at_is_flagged(link):
    v = score(link)
    assert any(r.code == "brand_mismatch" and r.evidence["where"] == "userinfo" for r in v.reasons)
    assert v.verdict != "green" and v.is_fraud is True
