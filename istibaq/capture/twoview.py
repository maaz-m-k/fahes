"""Two-view capture of a suspect page with Playwright.

The page is opened twice: as a **server** (plain headless desktop browser, the
way scanners and police tools look) and as a **phone** (mobile emulation).
Both views share the Arabic UAE locale and Gulf time zone; only the user agent
and viewport differ, so language is never mistaken for cloaking. Every redirect hop is
recorded (HTTP and client-side), each rendered step is screenshotted, human
check walls are detected (never solved), the two views are compared, and
"saw through" notes say what the agent overcame.

Safety: the capture only navigates. It never types, clicks, submits a form or
solves a challenge; dialogs are dismissed and downloads refused. Set
``ISTIBAQ_CAPTURE_LOCAL_ONLY=1`` on a laptop to refuse anything but 127.0.0.1.
Only http and https are fetched; every request and redirect hop is checked and
non-public addresses (loopback, private, link-local) are refused.
"""
from __future__ import annotations

import difflib
import hashlib
import ipaddress
import os
import re
import socket
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from istibaq.adapters.base import now_iso
from istibaq.adapters.contract import OnlineFacts

SERVER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "HeadlessChrome/126.0.0.0 Safari/537.36")
PHONE_DEVICE = "iPhone 13"
# Replay screenshots are shown large on the desk: capture sharp, lossless PNGs.
SERVER_SCALE = 2
PHONE_SCALE = 3

WALL_MARKERS = (
    "g-recaptcha", "recaptcha/api", "hcaptcha", "h-captcha", "challenges.cloudflare.com", "cf-challenge",
    "cf-turnstile", "turnstile", "just a moment...", "verify you are human", "are you a robot",
    "i'm not a robot", "checking your browser", "تحقق من أنك إنسان", "أنا لست روبوت",
)
BRAND_WORDS = {
    "TAMM": ("tamm", "تم"), "Abu Dhabi Police": ("abu dhabi police", "شرطة أبوظبي", "adpolice"),
    "Emirates NBD": ("emirates nbd", "الإمارات دبي الوطني"), "ADCB": ("adcb", "بنك أبوظبي التجاري"),
    "FAB": ("first abu dhabi bank", "بنك أبوظبي الأول"), "ADIB": ("adib", "مصرف أبوظبي الإسلامي"),
    "ICP": ("federal authority for identity", "الهيئة الاتحادية للهوية"), "Emirates Post": ("emirates post", "بريد الإمارات"),
    "ADDC": ("addc", "أبوظبي للتوزيع"), "Darb": ("darb", "درب"),
}
IBAN = re.compile(r"\bAE\d{2}\s?(?:\d{3}\s?)\d{16}\b|\bAE\d{21}\b")


class CaptureRefused(RuntimeError):
    pass


@dataclass
class Hop:
    url: str
    status: int | None
    kind: str   # "http" (server redirect), "client" (meta/JS), "final"


@dataclass
class Shot:
    url: str
    path: str
    sha256: str
    time: str


@dataclass
class View:
    name: str                     # "server" or "phone"
    user_agent: str
    hops: list[Hop] = field(default_factory=list)
    final_url: str = ""
    title: str = ""
    text: str = ""
    html_sha256: str = ""
    human_check_wall: bool = False
    wall_markers: list[str] = field(default_factory=list)
    screenshots: list[Shot] = field(default_factory=list)
    error: str = ""
    video: str = ""               # with record=True: a sped-up MP4 of this view (or the frames folder without ffmpeg)

    @property
    def chain(self) -> list[str]:
        return [h.url for h in self.hops]


@dataclass
class Capture:
    link: str
    started_at: str
    finished_at: str
    server: View
    phone: View
    differences: list[str]
    saw_through: list[str]
    facts: OnlineFacts
    failures: list[str] = field(default_factory=list)  # a view that failed: a fact, never a reason

    def to_dict(self) -> dict:
        d = asdict(self)
        d["facts"] = self.facts.to_dict()
        return d


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def detect_wall(html: str, title: str) -> list[str]:
    hay = (title + "\n" + html).lower()
    return [m for m in WALL_MARKERS if m in hay]


def detect_brand(title: str, text: str) -> str | None:
    """The official brand a page shows: the Genuine Register's names and brand words first."""
    try:
        from istibaq.core.pagebrand import page_brand
        hit = page_brand(title, text)
        if hit:
            return hit.brand.upper() if len(hit.brand) <= 5 else hit.brand
    except ImportError:  # scorer not installed: the short built-in list below
        pass
    hay = f"{title}\n{text}".lower()
    for brand, words in BRAND_WORDS.items():
        for w in words:
            if (len(w) <= 3 and re.search(rf"(?<!\w){re.escape(w)}(?!\w)", hay)) or (len(w) > 3 and w in hay):
                return brand
    return None


def _local_only() -> bool:
    return os.environ.get("ISTIBAQ_CAPTURE_LOCAL_ONLY", "").lower() in {"1", "true", "yes"}


def _blocked_ip(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return (a.is_loopback or a.is_private or a.is_link_local or a.is_multicast or a.is_reserved
            or a.is_unspecified or not a.is_global)


def check_url(url: str, local_only: bool | None = None, _cache: dict | None = None) -> str | None:
    """Return why ``url`` may not be fetched, or ``None`` when it is allowed.

    Only http and https. Local-only mode allows nothing but 127.0.0.1/localhost;
    otherwise every address the host resolves to must be public (no loopback,
    private, link-local, multicast or reserved), so capture cannot be aimed at
    the server itself or its internal network.
    """
    local_only = _local_only() if local_only is None else local_only
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        return f"malformed address ({e})"
    if parts.scheme not in {"http", "https"}:
        return f"scheme {parts.scheme or '(none)'} not allowed"
    host = (parts.hostname or "").lower()
    if not host:
        return "no host"
    if local_only:
        return None if host in {"127.0.0.1", "localhost"} else "local-only capture is on; refusing a non-local address"
    cache = _cache if _cache is not None else {}
    if host not in cache:
        try:
            ips = {ai[4][0] for ai in socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80))}
        except (socket.gaierror, UnicodeError):
            ips = set()
        # an unresolvable host is allowed through: the browser fails on its own (a dead-link fact)
        cache[host] = "non-public address" if any(_blocked_ip(i) for i in ips) else None
    return cache[host]


def _guard(link: str) -> None:
    why = check_url(link)
    if why:
        raise CaptureRefused(why)


def _view(browser, name: str, link: str, ctx_opts: dict, shots_dir: Path, timeout_ms: int, settle_ms: int,
          max_steps: int, record: bool = False, speed: float = 3.0) -> View:
    ctx = browser.new_context(accept_downloads=False, **ctx_opts)
    cache: dict = {}
    refused: list[str] = []

    def gate(route):
        url = route.request.url
        if url.startswith(("data:", "blob:")) and not route.request.is_navigation_request():
            return route.continue_()
        why = check_url(url, _cache=cache)
        if why:
            refused.append(f"{url}: {why}")
            return route.abort("blockedbyclient")
        # The browser follows redirects without consulting routes, so fetch each hop here
        # without following, check the next address, and hand the redirect back to the browser.
        try:
            resp = route.fetch(max_redirects=0)
        except Exception:
            return route.abort("failed")
        loc = resp.headers.get("location")
        if 300 <= resp.status < 400 and loc:
            nxt = urljoin(url, loc)
            why = check_url(nxt, _cache=cache)
            if why:
                refused.append(f"{nxt}: {why}")
                return route.abort("blockedbyclient")
        return route.fulfill(response=resp)

    ctx.route("**/*", gate)  # every request and every redirect hop is checked
    page = ctx.new_page()
    view = View(name, ctx_opts.get("user_agent") or page.evaluate("navigator.userAgent"))
    page.on("dialog", lambda d: d.dismiss())
    cast = None
    if record:  # real footage of this view at device resolution (the browser was launched with the same scale)
        from .footage import Screencast
        vp = ctx_opts["viewport"]; scale = ctx_opts.get("device_scale_factor", 1)
        cast = Screencast(ctx.new_cdp_session(page), shots_dir / f"{name}-frames",
                          {"width": vp["width"] * scale, "height": vp["height"] * scale})
        cast.start()

    def on_request(req):
        if req.is_navigation_request() and req.frame == page.main_frame:
            kind = "client" if (view.hops and req.redirected_from is None) else "http"
            if not view.hops:
                kind = "http"
            view.hops.append(Hop(req.url, None, kind))

    def on_response(resp):
        if resp.request.is_navigation_request() and resp.frame == page.main_frame:
            for h in reversed(view.hops):
                if h.url == resp.url and h.status is None:
                    h.status = resp.status
                    break

    page.on("request", on_request)
    page.on("response", on_response)
    try:
        page.goto(link, wait_until="load", timeout=timeout_ms)
        for i in range(max_steps):
            url = page.url
            path = shots_dir / f"{name}-{i:02d}.png"
            png = page.screenshot(path=str(path), type="png", full_page=False)
            view.screenshots.append(Shot(url, str(path), _sha(png), now_iso()))
            try:
                page.wait_for_url(lambda u, cur=url: u != cur, timeout=settle_ms)
                page.wait_for_load_state("load", timeout=timeout_ms)
            except Exception:
                break
        view.final_url = page.url
        view.title = page.title()
        html = page.content()
        view.html_sha256 = _sha(html.encode())
        view.text = page.inner_text("body")[:5000] if page.query_selector("body") else ""
        view.wall_markers = detect_wall(html, view.title)
        view.human_check_wall = bool(view.wall_markers)
    except Exception as e:  # dead links, timeouts, TLS failures are facts, not crashes
        view.error = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        view.final_url = view.final_url or page.url
    finally:
        if view.hops:
            # mark the last hop, collapse duplicates from reloads
            dedup: list[Hop] = []
            for h in view.hops:
                if not dedup or dedup[-1].url != h.url:
                    dedup.append(h)
            dedup[-1].kind = "final"
            view.hops = dedup
        if cast:
            page.wait_for_timeout(600)
            cast.stop()
            view.video = str(cast.folder)
            if cast.n:
                try:
                    from .footage import speed_up
                    view.video = str(speed_up(cast.folder, shots_dir / f"{name}.mp4", speed))
                except Exception:  # no ffmpeg: the frames folder is kept
                    pass
        ctx.close()
    if refused and not view.error:
        view.error = "Refused: " + refused[0][:200]
    elif refused:
        view.error += f" (refused: {refused[0][:150]})"
    return view


def failures(server: View, phone: View) -> list[str]:
    """Views that failed to load. Recorded as facts; never a difference or a reason."""
    return [f"{v.name} view did not load: {v.error}" for v in (server, phone) if v.error]


def compare(server: View, phone: View) -> list[str]:
    """Differences between two views that BOTH loaded. A failed view is never a difference."""
    if server.error or phone.error:
        return []
    diffs = []
    if server.final_url and phone.final_url and _host(server.final_url) != _host(phone.final_url):
        diffs.append(f"different destination: server ended at {_host(server.final_url)}, "
                     f"phone ended at {_host(phone.final_url)}")
    if server.human_check_wall != phone.human_check_wall:
        who = "server" if server.human_check_wall else "phone"
        diffs.append(f"human-check wall shown to the {who} view only")
    if server.title.strip() != phone.title.strip():
        diffs.append(f"different title: server '{server.title[:80]}', phone '{phone.title[:80]}'")
    ratio = difflib.SequenceMatcher(None, server.text[:3000], phone.text[:3000]).ratio()
    if ratio < 0.6:
        diffs.append(f"different page content (similarity {ratio:.2f})")
    return diffs


def saw_through_notes(server: View, phone: View, diffs: list[str]) -> list[str]:
    notes = []
    if diffs:
        notes.append("hidden from server: the page showed the server view something different from the phone view")
    for v in (server, phone):
        redirects = [h for h in v.hops if h.kind != "final"]
        if redirects:
            notes.append(f"redirect chain followed ({v.name}): {len(v.hops)} hops, "
                         + " -> ".join(_host(h.url) or h.url for h in v.hops))
        if v.human_check_wall:
            notes.append(f"human-check wall seen in the {v.name} view ({', '.join(v.wall_markers[:3])}); "
                         "recorded, not solved")
    return notes


def capture(link: str, out_dir: str | Path | None = None, timeout_ms: int = 20000, settle_ms: int = 2500,
            max_steps: int = 6, record: bool = False, speed: float = 3.0) -> Capture:
    """Capture ``link`` from the server and phone views. Never types or submits.

    ``record=True`` also records each view as real footage (a sped-up MP4 at device resolution), for the replay.
    """
    _guard(link)
    from playwright.sync_api import sync_playwright

    started = now_iso()
    shots_dir = Path(out_dir or tempfile.mkdtemp(prefix="istibaq-capture-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        def launch(scale: int | None = None):
            # recording takes the screencast in physical pixels, so the device scale is forced per view
            return p.chromium.launch(headless=True, args=[f"--force-device-scale-factor={scale}"] if scale else [])
        browser = launch(SERVER_SCALE if record else None)
        try:
            # Both views share locale, time zone and language; only user agent and viewport vary,
            # so a bilingual site is not mistaken for cloaking.
            common = {"locale": "ar-AE", "timezone_id": "Asia/Dubai",
                      "extra_http_headers": {"Accept-Language": "ar-AE,ar;q=0.9,en;q=0.5"}}
            server = _view(browser, "server", link,
                           {"user_agent": SERVER_UA, "viewport": {"width": 1280, "height": 800},
                            "device_scale_factor": SERVER_SCALE, **common},
                           shots_dir, timeout_ms, settle_ms, max_steps, record, speed)
            if record:
                browser.close()
                browser = launch(PHONE_SCALE)
            dev = p.devices[PHONE_DEVICE]
            phone_opts = {"user_agent": dev["user_agent"], "viewport": dev["viewport"],
                          "device_scale_factor": PHONE_SCALE, "is_mobile": dev["is_mobile"],
                          "has_touch": dev["has_touch"], **common}
            phone = _view(browser, "phone", link, phone_opts, shots_dir, timeout_ms, settle_ms, max_steps, record, speed)
        finally:
            browser.close()
    diffs = compare(server, phone)
    chain = phone.chain if len(phone.chain) >= len(server.chain) else server.chain
    payee = None
    m = IBAN.search(phone.text) or IBAN.search(server.text)
    if m:
        payee = m.group(0).replace(" ", "")
    walls = server.human_check_wall or phone.human_check_wall
    facts = OnlineFacts(
        redirect_chain=chain or None,
        two_view_difference="; ".join(diffs) or None,
        live_page_brand=detect_brand(phone.title, phone.text) or detect_brand(server.title, server.text),
        human_check_wall=walls if (server.final_url or phone.final_url) else None,
        payee=payee,
    )
    return Capture(link, started, now_iso(), server, phone, diffs, saw_through_notes(server, phone, diffs), facts,
                   failures(server, phone))
