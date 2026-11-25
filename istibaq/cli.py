"""Judges' offline command.

    istibaq score links.txt [--mode judging|officer] [--out results.csv] [--format csv|jsonl]

Input: one link per line, or a CSV with a ``url`` column. No keys, no internet.
``--online`` (server only, never on a laptop with suspect links) also follows short links and
redirects hop by hop through the capture address guard, and reads domain age from RDAP.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys

from .core.scorer import score_many

COLUMNS = ["link", "is_fraud", "score", "verdict", "reasons", "model_version", "scored_at"]


def read_links(text: str) -> list[str]:
    lines = text.splitlines()
    first = next((l for l in lines if l.strip()), "")
    if "," in first or first.strip().lower() in ("url", '"url"'):
        rows = list(csv.DictReader(io.StringIO(text)))
        if rows and any(k and k.strip().lower() == "url" for k in rows[0].keys()):
            key = next(k for k in rows[0].keys() if k and k.strip().lower() == "url")
            return [r[key].strip() for r in rows if r.get(key) and r[key].strip()]
    return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]


def _reasons_text(v) -> str:
    return " | ".join(f"{r.code}: {r.ar} / {r.en}" for r in v.reasons)


def write(verdicts, out, fmt: str) -> None:
    if fmt == "jsonl":
        for v in verdicts:
            out.write(json.dumps(v.to_dict(), ensure_ascii=False) + "\n")
        return
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for v in verdicts:
        w.writerow([v.link, "yes" if v.is_fraud else "no", f"{v.score:.4f}", v.verdict, _reasons_text(v),
                    v.model_version, v.scored_at])


def _online_facts(link: str):
    from .adapters.expand import online_facts
    from .adapters.rdap import RDAP
    return online_facts(link, rdap=RDAP())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="istibaq", description="Istibaq engine: score links offline.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="score a file of links (one per line, or CSV with a url column)")
    s.add_argument("file", help="input file, or - for stdin")
    s.add_argument("--mode", choices=["judging", "officer"], default="judging")
    s.add_argument("--out", help="output file (default: stdout)")
    s.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    s.add_argument("--online", action="store_true",
                   help="follow short links and redirects and read RDAP age (needs internet; run on the server)")
    args = p.parse_args(argv)

    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8-sig").read()
    links = read_links(text)
    online = None
    if args.online:
        online = {}
        for link in links:
            try:
                online[link] = _online_facts(link)
            except Exception as e:  # online facts are optional; the link is still scored offline
                print(f"online facts failed for one link: {type(e).__name__}", file=sys.stderr)
    verdicts = score_many(links, mode=args.mode, online_by_link=online)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            write(verdicts, f, args.format)
        flagged = sum(v.is_fraud for v in verdicts)
        print(f"scored {len(verdicts)} links, {flagged} flagged as fraud -> {args.out}", file=sys.stderr)
    else:
        write(verdicts, sys.stdout, args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
