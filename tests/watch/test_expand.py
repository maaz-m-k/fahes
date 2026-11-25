"""Following short links and redirects to where a link really lands (lever 3). Mock transport only."""
import httpx

from istibaq.adapters.expand import LinkExpander, online_facts
from istibaq.core.scorer import score


def _client(routes: dict[str, tuple[int, str | None]]):
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        code, loc = routes.get(str(req.url), (404, None))
        return httpx.Response(code, headers={"location": loc} if loc else {})
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def allow(url):
    return None


def test_follows_every_hop_without_letting_the_client_follow():
    c, seen = _client({"https://bit.ly/x": (301, "https://hop.example/a"),
                       "https://hop.example/a": (302, "/b"),
                       "https://hop.example/b": (200, None)})
    chain = LinkExpander(c, guard=allow).chain("https://bit.ly/x")
    assert chain.hops == ["https://bit.ly/x", "https://hop.example/a", "https://hop.example/b"]
    assert seen == chain.hops and chain.stopped is None


def test_every_hop_goes_through_the_address_guard():
    c, seen = _client({"https://bit.ly/x": (301, "http://127.0.0.1:8080/admin")})
    guard = lambda u: "non-public address" if "127.0.0.1" in u else None  # noqa: E731
    chain = LinkExpander(c, guard=guard).chain("https://bit.ly/x")
    assert chain.hops == ["https://bit.ly/x", "http://127.0.0.1:8080/admin"]
    assert "non-public" in chain.stopped and seen == ["https://bit.ly/x"]


def test_only_http_and_https_are_followed():
    c, seen = _client({"https://bit.ly/x": (302, "file:///etc/passwd")})
    chain = LinkExpander(c).chain("https://bit.ly/x")
    assert "scheme" in chain.stopped and seen == ["https://bit.ly/x"]


def test_hop_limit():
    c, _ = _client({f"https://loop.example/{i}": (302, f"https://loop.example/{i + 1}") for i in range(30)})
    chain = LinkExpander(c, guard=allow, max_hops=5).chain("https://loop.example/0")
    assert len(chain.hops) == 6 and "too many" in chain.stopped


def test_short_link_to_a_fake_is_judged_by_where_it_lands():
    c, _ = _client({"https://bit.ly/fine": (301, "https://tamm-pay.example/login"),
                    "https://tamm-pay.example/login": (200, None)})
    facts = online_facts("https://bit.ly/fine", expander=LinkExpander(c, guard=allow))
    v = score("https://bit.ly/fine", online=facts)
    assert v.is_fraud and v.verdict == "red", v.to_dict()
    assert "cross_domain_redirect" in {r.code for r in v.reasons}


def test_short_link_to_an_official_page_is_not_accused():
    c, _ = _client({"https://bit.ly/tamm": (301, "https://www.tamm.abudhabi/en"),
                    "https://www.tamm.abudhabi/en": (200, None)})
    facts = online_facts("https://bit.ly/tamm", expander=LinkExpander(c, guard=allow))
    v = score("https://bit.ly/tamm", online=facts)
    assert not v.is_fraud and v.verdict != "red"


def test_offline_short_link_stays_grey():
    v = score("https://bit.ly/fine")
    assert v.verdict == "grey" and not v.is_fraud
