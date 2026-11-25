"""Measure the AI second opinion: choose on the development split, then score the sealed test v2 once.

    python -m istibaq.eval.ai_second plan   --split dev --models google/gemini-2.5-flash-lite,openai/gpt-4.1-nano
    python -m istibaq.eval.ai_second fetch  --split dev --models ... --max-usd 1.0        # needs OPENROUTER_API_KEY
    python -m istibaq.eval.ai_second choose --models ...                                  # dev only; freezes ai_policy.json
    python -m istibaq.eval.ai_second plan   --split sealed                                # uses the frozen model
    python -m istibaq.eval.ai_second fetch  --split sealed --max-usd 1.0                  # needs OPENROUTER_API_KEY
    python -m istibaq.eval.ai_second sealed                                               # offline replay, logs runs

Every model answer is cached by address in ``ai_cache.jsonl`` and every call's cost in ``ai_spend.jsonl``,
so ``choose`` and ``sealed`` replay offline with no key. The known-bad list is off, as in
``istibaq.eval.accuracy``. The sealed file is never used to choose anything: ``sealed`` refuses to run
without the frozen policy, and the policy records the dev numbers it was chosen on.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from istibaq.core import second_opinion as so
from istibaq.eval.accuracy import RUNS, TESTSETS, load_sealed, summarise

HERE = Path(__file__).resolve().parent
CACHE = HERE / "ai_cache.jsonl"
SPEND = HERE / "ai_spend.jsonl"
POLICY = HERE / "ai_policy.json"
REPORT = HERE / "ai_sealed_report.json"
DEFAULT_MODELS = ["google/gemini-2.5-flash-lite", "openai/gpt-4.1-nano", "openai/gpt-4o-mini"]
TOTAL_LIMIT_USD = 3.0   # the whole experiment, across every model and split
STEADY = 0.005          # "catch steady": the catch rate may fall by at most half a point


def load_dev() -> list[dict]:
    manifest = json.loads((TESTSETS / "manifest_dev_ai.json").read_text())
    data = TESTSETS / manifest["file"]
    if hashlib.sha256(data.read_bytes()).hexdigest() != manifest["sha256"]:
        raise RuntimeError("dev split changed: SHA-256 does not match manifest_dev_ai.json")
    return [json.loads(x) for x in data.read_text().splitlines() if x.strip()]


def load(split: str) -> list[dict]:
    return load_dev() if split == "dev" else load_sealed()[0]


def baseline(rows: list[dict]) -> dict[str, list]:
    """Verdicts of the checker as it is on main, in both settings, known-bad list off."""
    from istibaq.core import scorer
    from istibaq.eval.scorecard import known_bad_off
    with known_bad_off():
        scorer.clear_cache()
        out = {m: scorer.score_many([r["link"] for r in rows], mode=m) for m in ("judging", "officer")}
    scorer.clear_cache()
    return out


def candidates(base: dict[str, list]) -> list[dict]:
    return [so.facts(v) for v in base["judging"] if so.eligible(v)]


def spent_total() -> float:
    if not SPEND.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in SPEND.read_text().splitlines() if l.strip())


def _sink(split: str):
    def sink(service: str, usd: float, detail: dict) -> None:
        with SPEND.open("a") as f:
            f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "service": service, "split": split, "usd": usd, **detail}) + "\n")
    return sink


def apply_all(base: dict[str, list], ops: dict, policy: so.Policy) -> dict[str, list]:
    return {m: [so.apply(v, ops.get(so.facts(v)["address"]) if so.eligible(v) else None, policy, m) for v in vs]
            for m, vs in base.items()}


def _brief(s: dict) -> dict:
    return {k: s[k] for k in ("catch_rate", "catch_range95", "false_alarms", "false_alarm_rate", "false_alarm_range95",
                              "caught", "fakes", "reals", "precision", "precision_range95", "precision_at_half_fakes")}


def measure(rows: list[dict], verdicts: dict[str, list]) -> dict:
    return {m: summarise(rows, [v.is_fraud for v in vs]) for m, vs in verdicts.items()}


def gain(before: dict, after: dict, settings=("judging", "officer")) -> float:
    """Dev objective: change in catch rate minus change in false-alarm rate, summed over settings.
    Minus infinity when precision drops in any setting."""
    g = 0.0
    for s in settings:
        b, a = before[s], after[s]
        if (a["precision"] or 0) < (b["precision"] or 0):
            return float("-inf")
        g += (a["catch_rate"] - b["catch_rate"]) - (a["false_alarm_rate"] - b["false_alarm_rate"])
    return round(g, 6)


def grid(idea: str) -> list[so.Policy]:
    if idea == "second_opinion":
        out = []
        for conf in (0.6, 0.7, 0.8, 0.9):
            for lo, hi in ((0.0, 1.01), (0.3, 1.01), (0.5, 1.01), (0.5, 0.99), (0.7, 0.99), (0.8, 1.01)):
                for r, c in ((True, True), (True, False), (False, True)):
                    out.append(so.Policy("second_opinion", conf, lo, hi, r, c))
        return out
    if idea == "builder_clear":
        return [so.Policy("builder_clear", conf) for conf in (0.6, 0.7, 0.8, 0.9, 0.95)]
    out = []
    for officer_only in (False, True):
        out.append(so.Policy(idea, officer_only=officer_only))
        for conf in (0.6, 0.8, 0.9):
            out.append(so.Policy(idea, conf, officer_only=officer_only, require_fake=True))
    return out


def ship_verdict(before: dict, after: dict) -> dict:
    """The rule the team set: ship only if, in both settings, precision does not drop and catch rises, or false
    alarms drop with catch steady; real UAE pages stay at 0 false alarms; popular-site false alarms do not rise."""
    why = []
    ok_any = False
    for s in ("judging", "officer"):
        b, a = before[s], after[s]
        if (a["precision"] or 0) < (b["precision"] or 0):
            why.append(f"{s}: precision dropped")
        uae = a["slices"].get("uae_real_pages", {}).get("flagged", 0)
        if uae:
            why.append(f"{s}: {uae} false alarms on real UAE pages")
        for sl in ("popular_sites", "popular_subdomains"):
            if a["slices"].get(sl, {}).get("flagged", 0) > b["slices"].get(sl, {}).get("flagged", 0):
                why.append(f"{s}: false alarms rose on {sl}")
        better = (a["caught"] > b["caught"]) or (a["false_alarms"] < b["false_alarms"]
                                                 and a["catch_rate"] >= b["catch_rate"] - STEADY)
        worse = a["caught"] < b["caught"] - STEADY * b["fakes"]
        if worse:
            why.append(f"{s}: catch fell")
        ok_any |= better
    if not ok_any:
        why.append("no improvement in either setting")
    return {"ship": not why, "why_not": why}


def _models(a) -> list[str]:
    return [m.strip() for m in (a.models or "").split(",") if m.strip()]


def _frozen() -> dict:
    if not POLICY.exists():
        raise SystemExit("no frozen policy: run `choose` on the dev split first")
    return json.loads(POLICY.read_text())


def cmd_plan(a) -> int:
    from istibaq.adapters.second_opinion import OpinionCache, plan
    rows = load(a.split)
    items = candidates(baseline(rows))
    models = _models(a) or ([_frozen()["model"]] if a.split == "sealed" else DEFAULT_MODELS)
    total = 0.0
    for m in models:
        p = plan(items, m, a.batch, OpinionCache(CACHE))
        total += p["est_usd"]
        print(json.dumps({"split": a.split, "rows": len(rows), **p}))
    print(f"estimated total ${total:.4f}; spent so far ${spent_total():.4f}; experiment limit ${TOTAL_LIMIT_USD:.2f}")
    return 0


def cmd_fetch(a) -> int:
    from istibaq.adapters.second_opinion import BudgetExceeded, OpinionCache, SecondOpinion
    rows = load(a.split)
    items = candidates(baseline(rows))
    models = _models(a) or ([_frozen()["model"]] if a.split == "sealed" else DEFAULT_MODELS)
    for m in models:
        room = min(a.max_usd, TOTAL_LIMIT_USD - spent_total())
        if room <= 0:
            print("experiment spend limit reached; stopping", file=sys.stderr)
            return 2
        c = SecondOpinion(model=m, cost_sink=_sink(a.split), cache=OpinionCache(CACHE), batch=a.batch,
                          workers=a.workers, max_usd=room)
        try:
            got = c.opinions(items)
        except BudgetExceeded as e:
            print(f"{m}: {e}", file=sys.stderr)
            return 2
        except Exception as e:  # one model failing (unknown name, outage) does not stop the others
            print(f"{m}: failed: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        print(json.dumps({"split": a.split, "model": m, "links": len(items), "answered": len(got),
                          "calls": c.calls, "usd": round(c.spent, 6)}))
    print(f"spent so far ${spent_total():.4f} of the ${TOTAL_LIMIT_USD:.2f} experiment limit")
    return 0


def cmd_choose(a) -> int:
    from istibaq.adapters.second_opinion import OpinionCache, PROMPT_VERSION
    rows = load_dev()
    base = baseline(rows)
    before = measure(rows, base)
    cache = OpinionCache(CACHE)
    n_cand = len(candidates(base))
    table, best_model, best_g = {}, None, float("-inf")
    for m in _models(a) or DEFAULT_MODELS:
        ops = cache.load(m)
        cover = sum(1 for f in candidates(base) if f["address"] in ops)
        if cover == 0:
            print(f"{m}: no cached answers on dev; skipped")
            continue
        per = {"coverage": [cover, n_cand]}
        for idea in so.IDEAS:
            settings = ("judging",) if idea in ("second_opinion", "builder_clear") else ("judging", "officer")
            scored = []
            for pol in grid(idea):
                after = measure(rows, apply_all(base, ops, pol))
                scored.append((gain(before, after, settings), pol, after))
            g, pol, after = max(scored, key=lambda t: t[0])
            per[idea] = {"policy": pol.__dict__, "dev_gain": g,
                         "dev_after": {s: _brief(after[s]) for s in ("judging", "officer")}}
        table[m] = per
        g1 = per["second_opinion"]["dev_gain"]
        print(f"{m}: coverage {cover}/{n_cand}; " + "; ".join(f"{i} {per[i]['dev_gain']}" for i in so.IDEAS))
        if g1 > best_g:
            best_model, best_g = m, g1
    if best_model is None:
        raise SystemExit("no model has cached dev answers")
    frozen = {
        "frozen_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chosen_on": "dev split only (istibaq/data/testsets/dev_ai.jsonl)",
        "prompt_version": PROMPT_VERSION,
        "model": best_model,
        "model_rule": "highest dev gain for the second opinion (catch-rate change minus false-alarm-rate change, "
                      "precision may not drop)",
        "policies": {i: table[best_model][i]["policy"] for i in so.IDEAS},
        "dev_before": {s: _brief(before[s]) for s in ("judging", "officer")},
        "dev": table,
    }
    POLICY.write_text(json.dumps(frozen, indent=2, ensure_ascii=False) + "\n")
    print(f"frozen -> {POLICY} (model {best_model})")
    return 0


def cmd_sealed(a) -> int:
    from istibaq.adapters.second_opinion import OpinionCache
    from istibaq.core import scorer
    frozen = _frozen()
    rows, manifest = load_sealed()
    base = baseline(rows)
    ops = OpinionCache(CACHE).load(frozen["model"])
    cands = candidates(base)
    cover = sum(1 for f in cands if f["address"] in ops)
    before = measure(rows, base)
    try:
        commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    report = {"model": frozen["model"], "prompt_version": frozen["prompt_version"], "policy_frozen_at": frozen["frozen_at"],
              "testset_sha256": manifest["sha256"], "coverage": [cover, len(cands)],
              "before": {s: _brief(before[s]) | {"slices": before[s]["slices"]} for s in before}, "ideas": {}}
    for idea, p in frozen["policies"].items():
        pol = so.Policy(**p)
        after = measure(rows, apply_all(base, ops, pol))
        verdict = ship_verdict(before, after)
        report["ideas"][idea] = {"policy": p, "after": {s: _brief(after[s]) | {"slices": after[s]["slices"]}
                                                         for s in after}, **verdict}
        if not a.no_log:
            rec = {"label": f"AI {idea} ({frozen['model']}, policy frozen {frozen['frozen_at']}): offline replay",
                   "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": commit,
                   "model_version": scorer.model_version(), "testset_sha256": manifest["sha256"], "known_bad": "off",
                   "ai": {"model": frozen["model"], "policy": p, "coverage": [cover, len(cands)]}, **after}
            with RUNS.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for s in ("judging", "officer"):
            b, x = before[s], after[s]
            print(f"{idea:22} {s:8} catch {b['catch_rate']:.1%} -> {x['catch_rate']:.1%} {x['catch_range95']}  "
                  f"false alarms {b['false_alarms']} -> {x['false_alarms']} {x['false_alarm_range95']}  "
                  f"precision {b['precision']} -> {x['precision']} {x['precision_range95']}  "
                  f"UAE pages {x['slices']['uae_real_pages']['flagged']}  popular {x['slices']['popular_sites']['flagged']}")
        print(f"{idea:22} ship: {verdict['ship']} {verdict['why_not']}")
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"coverage {cover}/{len(cands)}; report -> {REPORT}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m istibaq.eval.ai_second")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "fetch"):
        p = sub.add_parser(name)
        p.add_argument("--split", choices=["dev", "sealed"], required=True)
        p.add_argument("--models", help="comma-separated OpenRouter model ids (sealed: the frozen model)")
        p.add_argument("--batch", type=int, default=20)
        if name == "fetch":
            p.add_argument("--max-usd", type=float, default=1.0, help="limit for this command")
            p.add_argument("--workers", type=int, default=4)
    p = sub.add_parser("choose")
    p.add_argument("--models")
    p = sub.add_parser("sealed")
    p.add_argument("--no-log", action="store_true")
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "fetch": cmd_fetch, "choose": cmd_choose, "sealed": cmd_sealed}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
