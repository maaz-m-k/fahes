"""The AI second-opinion measurement: the dev objective, the ship rule, and the offline replay."""
from istibaq.core import second_opinion as so
from istibaq.eval import ai_second as A


def s(caught, fakes, fa, reals, uae=0, popular=0, subs=0):
    tp, fp = caught, fa
    return {"caught": caught, "fakes": fakes, "false_alarms": fa, "reals": reals,
            "catch_rate": caught / fakes, "false_alarm_rate": fa / reals,
            "precision": tp / (tp + fp) if tp + fp else None,
            "slices": {"uae_real_pages": {"flagged": uae}, "popular_sites": {"flagged": popular},
                       "popular_subdomains": {"flagged": subs}}}


BEFORE = {"judging": s(700, 1000, 300, 6000, subs=290), "officer": s(200, 1000, 10, 6000, subs=10)}


def test_gain_rewards_catch_and_punishes_false_alarms_and_forbids_a_precision_drop():
    more_catch = {"judging": s(750, 1000, 300, 6000), "officer": BEFORE["officer"]}
    assert A.gain(BEFORE, more_catch) > 0
    fewer_fa = {"judging": s(700, 1000, 100, 6000), "officer": BEFORE["officer"]}
    assert A.gain(BEFORE, fewer_fa) > 0
    worse_precision = {"judging": s(720, 1000, 600, 6000), "officer": BEFORE["officer"]}
    assert A.gain(BEFORE, worse_precision) == float("-inf")


def test_ship_rule():
    ok = {"judging": s(700, 1000, 100, 6000, subs=90), "officer": BEFORE["officer"]}
    assert A.ship_verdict(BEFORE, ok)["ship"]
    uae = {"judging": s(700, 1000, 100, 6000, uae=1, subs=90), "officer": BEFORE["officer"]}
    assert not A.ship_verdict(BEFORE, uae)["ship"]
    popular_up = {"judging": s(760, 1000, 300, 6000, popular=5, subs=285), "officer": BEFORE["officer"]}
    assert not A.ship_verdict(BEFORE, popular_up)["ship"]
    catch_fell = {"judging": s(650, 1000, 100, 6000, subs=90), "officer": BEFORE["officer"]}
    assert not A.ship_verdict(BEFORE, catch_fell)["ship"]
    nothing = A.ship_verdict(BEFORE, BEFORE)
    assert not nothing["ship"] and "no improvement in either setting" in nothing["why_not"]


def test_every_idea_has_a_grid_of_valid_policies():
    for idea in so.IDEAS:
        g = A.grid(idea)
        assert g and all(p.idea == idea for p in g)


def test_replay_applies_cached_opinions_by_address():
    from istibaq.core.scorer import score
    rows = [{"link": "x7k2.pages.dev", "label": 0, "slice": "popular_subdomains", "counted": True},
            {"link": "mybakery.example", "label": 1, "slice": "fresh_fakes_phishtank", "counted": True},
            {"link": "u.ae", "label": 0, "slice": "uae_real_pages", "counted": True}]
    base = {m: [score(r["link"], m) for r in rows] for m in ("judging", "officer")}
    assert [f["address"] for f in A.candidates(base)] == ["x7k2.pages.dev", "mybakery.example"]
    ops = {"x7k2.pages.dev": so.Opinion("real", 0.95, model="m"), "mybakery.example": so.Opinion("fake", 0.95, model="m"),
           "u.ae": so.Opinion("fake", 1.0, model="m")}
    after = A.measure(rows, A.apply_all(base, ops, so.Policy("second_opinion", 0.8, 0.0, 1.01)))
    assert after["judging"]["caught"] == 1 and after["judging"]["false_alarms"] == 0
