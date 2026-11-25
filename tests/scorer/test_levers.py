"""Accuracy levers, tested through the public seam ``score()`` (reserved names for invented fakes)."""
import pytest

from istibaq.core.scorer import score


def codes(v):
    return {r.code for r in v.reasons}


# ---------- known misses (lever 6) ----------

def test_backslash_disguise_is_red():
    v = score("evil.test\\@adpolice.gov.ae")
    assert v.verdict == "red" and v.is_fraud, v.to_dict()
    assert {"brand_mismatch", "disguised_address"} <= codes(v)


def test_userinfo_disguise_is_red():
    v = score("http://adpolice.gov.ae@evil.test/pay", mode="officer")
    assert v.verdict == "red" and v.is_fraud, v.to_dict()


def test_bank_name_joined_with_bank_word_is_caught():
    v = score("adcbank-online.test")
    assert "brand_mismatch" in codes(v)
    assert v.is_fraud


def test_official_address_with_dot_turned_into_hyphen_is_caught():
    v = score("u-ae.online")
    assert "brand_mismatch" in codes(v)
    assert v.is_fraud
    v = score("adpolice-gov-ae.test")
    assert "brand_mismatch" in codes(v)


@pytest.mark.parametrize("plain", ["uae.example", "fabric.test", "adcbx.test", "unbank.test"])
def test_short_brand_rules_do_not_fire_on_plain_words(plain):
    assert "brand_mismatch" not in codes(score(plain))


@pytest.mark.parametrize("link", ["login-secure-bank.pages.dev", "verify-account-wallet.vercel.app",
                                  "kyc-update.netlify.app", "signin-recover.web.app", "secure-login.github.io"])
def test_free_builder_with_account_words_gets_a_second_reason(link):
    v = score(link, mode="officer")
    assert "lure_words" in codes(v)
    assert v.verdict == "red", v.to_dict()


@pytest.mark.parametrize("link", ["myportfolio.github.io", "docs-site.pages.dev", "weatherapp.vercel.app"])
def test_plain_free_builder_pages_are_not_red(link):
    v = score(link, mode="officer")
    assert v.verdict != "red" and not v.is_fraud


# ---------- false alarms the sealed test showed (lever 0) ----------

@pytest.mark.parametrize("link", ["0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.0.0.0.6.0.8.4.0.6.8.4.1.0.0.2.ip6.arpa",
                                  "10.26.213.23.in-addr.arpa"])
def test_reverse_dns_names_are_not_accused(link):
    for mode in ("judging", "officer"):
        v = score(link, mode=mode)
        assert not v.is_fraud and v.verdict == "grey"
        assert "infrastructure_name" in codes(v)


def test_subdomain_of_popular_owner_is_not_accused_on_address_alone():
    v = score("07c0aec6173f.cdn4.forter.com")
    assert not v.is_fraud, v.to_dict()
    assert "popular_owner" in codes(v)


def test_subdomain_of_popular_owner_with_brand_is_still_judged():
    v = score("tamm-pay.cdn4.forter.com")
    assert "brand_mismatch" in codes(v) and v.is_fraud


def test_free_host_subdomain_is_not_popular_owner():
    assert "popular_owner" not in codes(score("abc-login.github.io"))


def test_subdomain_providers_phishers_used_before_the_cut_get_no_owner_pass():
    # eu.cc is popular but hands out subdomains; PhishTank rows before the cut show phishing on several.
    assert "popular_owner" not in codes(score("random-name.eu.cc"))


# ---------- domain age offline (lever 2) ----------

def test_new_domain_from_bundled_list_has_source_and_day():
    from istibaq.core.reasons import new_domains
    nd, meta = new_domains()
    assert "0--k.com" in nd and "google.com" not in nd
    assert "hagezi" in meta["source"] and meta["list_date"].startswith("2026-")
    v = score("http://0--k.com/login")
    r = next(r for r in v.reasons if r.code == "new_domain")
    assert r.online is False and r.evidence["list_date"] == meta["list_date"]


def test_popular_site_is_not_new():
    assert "new_domain" not in codes(score("microsoft.com"))


# ---------- bigger Genuine Register (lever 1) ----------

@pytest.mark.parametrize("link", ["https://www.ewec.ae/en", "https://www.adx.ae/", "https://www.dfm.ae/",
                                  "https://www.adgm.com/", "https://www.difc.ae/", "https://www.daman.ae/",
                                  "https://www.malaffi.ae/", "https://uaecabinet.ae/", "https://www.zand.ae/",
                                  "https://www.almasraf.ae/", "https://www.investbank.ae/", "https://www.nbq.ae/"])
def test_more_real_uae_sites_are_green(link):
    v = score(link)
    assert v.verdict == "green", v.to_dict()
    assert v.reasons[0].evidence["source"] and v.reasons[0].evidence["date"]


def test_every_register_entry_has_source_and_date():
    from istibaq.core import register
    d = register.data()
    for f in d["families"]:
        assert f["source"] and f["date"]
    for h in d["helplines"]:
        assert h["source"].startswith("https://") and h["date"] and h["family"] and h["number"].isdigit()


# ---------- brand check on live pages (lever 4) ----------

from istibaq.core.contract import OnlineFacts  # noqa: E402
from istibaq.core.pagebrand import page_brand  # noqa: E402


@pytest.mark.parametrize("title,text,brand", [
    ("Pay your traffic fine | TAMM", "", "tamm"),
    ("Login", "Welcome to ADCB Online Banking", "adcb"),
    ("شرطة أبوظبي - دفع المخالفات", "", "abu_dhabi_police"),
    ("Emirates NBD | Verify", "", "emiratesnbd"),
])
def test_page_brand_comes_from_the_register(title, text, brand):
    b = page_brand(title, text)
    assert b is not None and brand in (b.brand, b.family)


def test_page_with_no_official_brand():
    assert page_brand("My cooking blog", "recipes and photos") is None


def test_free_builder_page_showing_a_uae_bank_is_red():
    v = score("x7k2.pages.dev", mode="officer", online=OnlineFacts(live_page_brand="adcb"))
    assert "live_brand_mismatch" in codes(v) and v.verdict == "red"


def test_official_page_showing_its_own_brand_is_green():
    v = score("https://www.adcb.com/en/", online=OnlineFacts(live_page_brand="adcb"))
    assert v.verdict == "green"


# ---------- review findings ----------

@pytest.mark.parametrize("link", ["authorportfolio.github.io", "definedesign.pages.dev", "hotpotcafe.netlify.app"])
def test_lure_words_are_whole_words_only(link):
    v = score(link, mode="officer")
    assert "lure_words" not in codes(v) and v.verdict != "red"


def test_a_dotted_user_name_is_not_a_disguise():
    v = score("http://ftp.user@files.example.org/")
    assert "disguised_address" not in codes(v)


def test_sorted_names_without_trailing_newline():
    from istibaq.core.reasons import SortedNames
    s = SortedNames(b"a.com\nb.com")
    assert "a.com" in s and "b.com" in s and "c.com" not in s
