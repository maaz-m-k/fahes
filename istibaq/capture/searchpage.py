"""The Fahes search page: a plain search page served by the engine that the recorded browser opens.

The results are the REAL results from the engine's search adapters (Brave web results; Google Places for the
questions marked ``maps``, as a Maps-style list with name, phone and website), each with Fahes's verdict chip.
The footage of the agent typing and scrolling here is labelled "Real results · Fahes search page".
Desktop and phone layouts come from the same page (it is responsive).
"""
from __future__ import annotations

import html
from typing import Callable, Iterable
from urllib.parse import quote_plus, urlparse

CHIP = {"green": ("رسمي", "Official", "#0f8a4a"), "grey": ("غير رسمي، بلا اتهام", "Not official, not accused", "#5e6763"),
        "red": ("مشتبه به", "Suspected", "#c2002f")}

STYLE = """
*{box-sizing:border-box}body{margin:0;font:16px/1.5 'IBM Plex Sans Arabic',system-ui,sans-serif;background:#f6f8f8;color:#16262a}
header{display:flex;align-items:center;gap:14px;padding:14px 22px;background:#fff;border-bottom:1px solid #e3e8e8;position:sticky;top:0}
.logo{font:700 22px system-ui;color:#0a4d4a;white-space:nowrap}.logo i{display:inline-block;width:18px;height:18px;border-radius:50%;margin-inline-end:8px;background:radial-gradient(circle at 30% 30%,#a7f3d0,#0f8b8d 60%,#0a4d4a);vertical-align:-3px}
form{flex:1;display:flex}input{flex:1;font:inherit;padding:11px 18px;border:1px solid #cfd8d8;border-radius:999px;outline:none;background:#fff;min-width:0}
input:focus{border-color:#0f8b8d;box-shadow:0 0 0 3px #0f8b8d22}
.label{margin:12px 22px 0;display:inline-block;padding:4px 12px;border-radius:999px;background:#e3f6ee;color:#0b6b43;font:600 13px system-ui}
main{max-width:780px;padding:6px 22px 60px}.r{display:block;text-decoration:none;color:inherit;background:#fff;border:1px solid #e3e8e8;border-radius:14px;padding:14px 16px;margin:12px 0}
.r:hover{border-color:#0f8b8d}.u{direction:ltr;text-align:left;color:#3c6e5e;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.t{color:#1a3fa8;font-size:18px;margin:2px 0}.s{color:#4b5b5f;font-size:14px}.chip{display:inline-block;margin-top:8px;padding:2px 10px;border-radius:999px;color:#fff;font:600 12px system-ui}
.maps{border-inline-start:4px solid #f2a33a}.maps .k{font-size:12px;color:#a86600;font-weight:600}
.home{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:80vh;gap:22px;padding:20px}
.home .logo{font-size:44px}.home form{flex:none;width:min(640px,100%)}
@media (max-width:600px){header{flex-wrap:wrap;padding:12px}.logo{font-size:19px}main{padding:4px 12px 40px}.t{font-size:17px}}
"""


def _page(body: str, lang: str = "ar") -> str:
    d = "rtl" if lang == "ar" else "ltr"
    return (f"<!doctype html><html lang='{lang}' dir='{d}'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>فاحص · بحث</title>"
            f"<style>{STYLE}</style></head><body>{body}</body></html>")


def render_home(lang: str = "ar") -> str:
    ph = "اسأل كما يسأل المقيم…" if lang == "ar" else "Ask the way a resident asks…"
    return _page(f"<div class='home'><div class='logo'><i></i>فاحص</div>"
                 f"<form action='/search/results'><input name='q' autocomplete='off' placeholder='{ph}'></form></div>", lang)


def render_results(q: str, results: Iterable[dict], label: str = "Real results · Fahes search page", lang: str = "ar") -> str:
    """``results``: dicts with ``title``, ``link``, ``snippet``, ``kind`` ("organic", "ad", "maps") and ``verdict``."""
    items = []
    for r in results:
        v = r.get("verdict") or "grey"
        ar, en, col = CHIP.get(v, CHIP["grey"])
        host = urlparse(r.get("link", "")).hostname or ""
        kind = r.get("kind", "organic")
        k = "<div class='k'>خرائط · Maps</div>" if kind == "maps" else ("<div class='k'>إعلان · Ad</div>" if kind == "ad" else "")
        items.append(f"<a class='r{' maps' if kind == 'maps' else ''}' href='{html.escape(r.get('link', ''), quote=True)}'>{k}"
                     f"<div class='u'>{html.escape(host)}</div><div class='t'>{html.escape(r.get('title', ''))}</div>"
                     f"<div class='s'>{html.escape(r.get('snippet', ''))}</div>"
                     f"<span class='chip' style='background:{col}'>فاحص: {ar} · {en}</span></a>")
    body = (f"<header><div class='logo'><i></i>فاحص</div><form action='/search/results'>"
            f"<input name='q' value='{html.escape(q, quote=True)}' autocomplete='off'></form></header>"
            f"<div class='label'>{html.escape(label)}</div><main>{''.join(items) or '<p>—</p>'}</main>")
    return _page(body, lang)


def live_results(q: str, maps: bool = False, lang: str = "ar", searchers: list | None = None,
                 score: Callable | None = None, cost_sink=None) -> list[dict]:
    """Real results from the engine's adapters (Brave, and Places when ``maps``), each scored by Fahes."""
    from istibaq.adapters.search import BraveSearch, PlacesSearch
    from istibaq.watch.scoring import get_scorer
    score = score or get_scorer()
    kw = {"cost_sink": cost_sink} if cost_sink else {}
    searchers = searchers if searchers is not None else ([BraveSearch(**kw)] + ([PlacesSearch(**kw)] if maps else []))
    out: list[dict] = []
    for s in searchers:
        for r in s.search(q, lang):
            d = r.to_dict()
            d["verdict"] = score(r.link, mode="officer").verdict
            out.append(d)
    return out


def results_url(base: str, q: str) -> str:
    return base.rstrip("/") + "/search/results?q=" + quote_plus(q)
