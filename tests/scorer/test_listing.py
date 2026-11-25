"""Maps listings are judged by name, phone and website (lever 5)."""
from istibaq.core.listing import judge_listing


def codes(v):
    return {r.code for r in v.reasons}


def test_police_listing_with_unofficial_phone_is_suspicious():
    v = judge_listing("Abu Dhabi Police fines help desk", phone="+971 50 123 4567", website=None)
    assert "listing_phone_not_official" in codes(v)
    assert v.verdict == "grey" and v.reasons[0].ar and v.reasons[0].en
    r = next(r for r in v.reasons if r.code == "listing_phone_not_official")
    assert "8002626" in r.evidence["official_numbers"]


def test_bank_listing_with_unofficial_phone_and_site_is_red():
    v = judge_listing("FAB Bank customer care", phone="04 555 1234", website="http://fab-care.example/", mode="officer")
    assert {"listing_phone_not_official", "listing_site_not_official"} <= codes(v)
    assert v.verdict == "red" and v.is_fraud


def test_official_listing_is_not_accused():
    v = judge_listing("Abu Dhabi Police GHQ", phone="800 2626", website="https://www.adpolice.gov.ae/")
    assert v.verdict == "green" and not v.is_fraud
    assert not codes(v) & {"listing_phone_not_official", "listing_site_not_official"}


def test_official_phone_in_any_form_matches():
    for p in ("+971 600 52 2222", "00971600522222", "600522222", "600-52-2222"):
        v = judge_listing("ICP customer happiness", phone=p, website=None)
        assert "listing_phone_not_official" not in codes(v), p


def test_listing_that_names_no_official_body_is_not_judged_by_name():
    v = judge_listing("Some cafe", phone="02 123 4567", website=None)
    assert not v.reasons and v.verdict == "grey" and not v.is_fraud


def test_listing_with_website_keeps_the_link_reasons():
    v = judge_listing("Fines Payment Center", phone=None, website="http://adpolice-fines.example/")
    assert "brand_mismatch" in codes(v)


def test_short_international_toll_free_form_matches():
    from istibaq.core.listing import phone_key
    assert phone_key("971800555") == phone_key("800555") == "800555"
