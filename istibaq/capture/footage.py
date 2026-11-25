"""Real footage of the agent working like a resident, for the replay on the desk.

``record_search(question, out_dir, view=...)`` drives a real Chromium session and records it as video
(Chromium's own screencast of the page at full device resolution, so it stays sharp; Playwright's built-in
recorder captures at CSS-pixel size only): it opens the search
page, moves a visible pointer (computer) or taps with a visible finger dot (phone, iPhone mode with touch),
types the question letter by letter at a human pace, scrolls the results, opens the first result that is
an official register page, and scrolls it. ``speed_up`` turns the recording into a sped-up H.264 MP4.

Safety, as in capture:
- typing happens only in the search engine's own search box; nothing is typed, clicked to submit, or solved
  on any other page;
- only official (green register) results are ever opened; a page that lands off the register is left at once;
- every request goes through the same address guard as capture (``check_url``), and
  ``ISTIBAQ_CAPTURE_LOCAL_ONLY=1`` refuses anything but 127.0.0.1;
- a robot check is never solved or bypassed: it is recorded, and the next search provider is tried.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote_plus, urlparse

from .twoview import PHONE_DEVICE, PHONE_SCALE, SERVER_SCALE, SERVER_UA, check_url, detect_wall

# search pages a resident would use; Google first, Brave Search as the real alternative
PROVIDERS = {
    "google": {"home": "https://www.google.com/?hl=ar", "box": "textarea[name=q], input[name=q]",
               "results": "#search a:has(h3)"},
    "brave": {"home": "https://search.brave.com/", "box": "#searchbox, input[name=q], textarea[name=q]",
              "results": "a[href^='http']"},
    "duckduckgo": {"home": "https://duckduckgo.com/?kl=xa-ar", "box": "input[name=q], textarea[name=q]",
                   "results": "a[data-testid='result-title-a'], a[href^='http']"},
    "mojeek": {"home": "https://www.mojeek.com/", "box": "input[name=q]", "results": "ul.results-standard a[href^='http']"},
}
def fahes_provider(base: str) -> dict:
    """Our own search page (``/search`` on the engine): real live results from the search adapters, with verdicts."""
    return {"fahes": {"home": base.rstrip("/") + "/search", "box": "input[name=q]", "results": "a.r"}}


OWN_HOSTS = ("google.", "gstatic.", "brave.com", "brave.app", "duckduckgo.com", "duck.ai", "hackerone.com", "mojeek.")
ROBOT = ("unusual traffic", "not a robot", "/sorry/", "captcha", "verify you are human", "are you a robot",
         "select all squares", "unexpected error. please try again", "bots use duckduckgo", "automated queries",
         "حركة مرور غير عادية", "لست روبوت")

# Draws the pointer (computer) or a finger dot (phone) that follows the real input events, since
# Playwright's video does not show one. Read-only: it never changes the page's behaviour.
POINTER_JS = r"""
(() => {
  if (window.__fahesPointer) return; window.__fahesPointer = 1;
  const touch = navigator.maxTouchPoints > 0;
  const put = () => {
    if (!document.documentElement) return requestAnimationFrame(put);
    const d = document.createElement('div');
    d.setAttribute('aria-hidden', 'true');
    d.style.cssText = 'position:fixed;z-index:2147483647;left:0;top:0;pointer-events:none;will-change:transform;transform:translate(-200px,-200px)';
    d.innerHTML = touch
      ? '<div style="width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;background:rgba(15,139,141,.35);border:3px solid rgba(15,139,141,.95);box-shadow:0 0 12px rgba(0,0,0,.35);opacity:0;transition:opacity .18s"></div>'
      : '<svg width="26" height="26" viewBox="0 0 24 24" style="filter:drop-shadow(0 1px 2px rgba(0,0,0,.5))"><path d="M4 2l6.5 19 2.6-7.4L21 11z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg><div style="position:absolute;left:-14px;top:-14px;width:28px;height:28px;border-radius:50%;border:3px solid #0F8B8D;opacity:0;transition:opacity .3s, transform .3s;transform:scale(.4)"></div>';
    document.documentElement.appendChild(d);
    const dot = d.firstElementChild, ring = d.lastElementChild;
    const at = (x, y) => { d.style.transform = `translate(${x}px,${y}px)`; try { sessionStorage.__fp = x + ',' + y; } catch (e) {} };
    try { const p = (sessionStorage.__fp || '').split(','); if (p.length === 2) at(+p[0], +p[1]); } catch (e) {}
    addEventListener('mousemove', e => at(e.clientX, e.clientY), true);
    addEventListener('mousedown', () => { if (!touch) { ring.style.opacity = 1; ring.style.transform = 'scale(1)'; setTimeout(() => { ring.style.opacity = 0; ring.style.transform = 'scale(.4)'; }, 320); } }, true);
    const tp = e => { const t = e.touches[0] || e.changedTouches[0]; if (t) at(t.clientX, t.clientY); };
    addEventListener('touchstart', e => { tp(e); dot.style.opacity = 1; }, true);
    addEventListener('touchmove', tp, true);
    addEventListener('touchend', () => setTimeout(() => { dot.style.opacity = 0; }, 160), true);
  };
  put();
})();
"""


@dataclass
class Moment:
    t_ms: int        # milliseconds from the start of the recording (real time)
    action: str      # "open", "type", "search", "scroll", "robot", "skip", "click", "left", "done"
    ar: str
    en: str
    url: str = ""


@dataclass
class Footage:
    question: str
    view: str                  # "computer" or "phone"
    provider: str = ""         # the provider whose results the footage shows
    video: str = ""            # the raw recording: a folder of timed frames (see ``speed_up``)
    width: int = 0
    height: int = 0
    moments: list[Moment] = field(default_factory=list)
    robot_checks: list[str] = field(default_factory=list)
    opened: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_official(url: str) -> bool:
    """Green register page: the only kind of result the footage ever opens."""
    from istibaq.core.register import lookup
    return lookup(url).status == "official"


def _robot(page) -> bool:
    try:
        text = (page.url + " " + page.title() + " " + page.inner_text("body")[:2000]).lower()
        html = page.content()[:20000]
    except Exception:
        return False
    return any(w in text for w in ROBOT) or bool(detect_wall(html, page.title()))


def record_search(question: str | list[str], out_dir: str | Path, view: str = "computer", providers=("google", "brave", "duckduckgo", "mojeek"),
                  official: Callable[[str], bool] = is_official, headless: bool = True,
                  provider_urls: dict | None = None, type_delay_ms: int = 110, extra_headers: dict | None = None,
                  trusted_origins: Iterable[str] = ()) -> Footage:
    """Record a resident search as real video; a list of questions records an overview (one after another).

    ``provider_urls`` overrides PROVIDERS: ``fahes_provider(base)`` is our own search page, and tests use a local page.
    """
    from playwright.sync_api import sync_playwright

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    fx = Footage(question if isinstance(question, str) else " | ".join(question), view)
    provs = {**PROVIDERS, **(provider_urls or {})}
    t0 = time.monotonic(); t0_wall = time.time()
    def mark(action, ar, en, url=""):
        fx.moments.append(Moment(int((time.monotonic() - t0) * 1000), action, ar, en, url))

    with sync_playwright() as p:
        # the screencast is taken in physical pixels, so force the device scale at the browser level too
        force = PHONE_SCALE if view == "phone" else SERVER_SCALE
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled",
                                                             f"--force-device-scale-factor={force}"])
        common = {"locale": "ar-AE", "timezone_id": "Asia/Dubai", "accept_downloads": False,
                  "extra_http_headers": {"Accept-Language": "ar-AE,ar;q=0.9,en;q=0.5", **(extra_headers or {})}}
        if view == "phone":
            dev = p.devices[PHONE_DEVICE]
            vp, scale = dev["viewport"], PHONE_SCALE
            opts = {"user_agent": dev["user_agent"], "viewport": vp, "device_scale_factor": scale,
                    "is_mobile": True, "has_touch": True, **common}
        else:
            vp, scale = {"width": 1280, "height": 800}, SERVER_SCALE
            opts = {"user_agent": SERVER_UA.replace("X11; Linux x86_64", "Macintosh; Intel Mac OS X 10_15_7"),
                    "viewport": vp, "device_scale_factor": scale, **common}
        size = {"width": vp["width"] * scale, "height": vp["height"] * scale}
        fx.width, fx.height = size["width"], size["height"]
        ctx = browser.new_context(**opts)
        cache: dict = {}
        own = tuple(o.rstrip("/") for o in (trusted_origins or ()))  # our own search page (the engine itself)

        def gate(route):  # the address guard: every page the browser goes to is checked first
            req = route.request
            mine = any(req.url == o or req.url.startswith(o + "/") for o in own)
            if req.is_navigation_request() and not mine and check_url(req.url, _cache=cache):
                return route.abort("blockedbyclient")
            return route.continue_()
        ctx.route("**/*", gate)
        ctx.add_init_script(POINTER_JS)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.dismiss())
        cdp = ctx.new_cdp_session(page)
        frames = out / f"{view}-{int(time.time())}"
        cast = Screencast(cdp, frames, size)
        cast.start()
        W, H = vp["width"], vp["height"]
        pos = [W * 0.5, H * 0.6]

        def move(x, y, steps=18):
            if view == "phone":
                pos[:] = [x, y]; return
            page.mouse.move(x, y, steps=steps); pos[:] = [x, y]

        def press_on(el):
            el.scroll_into_view_if_needed(timeout=5000)
            b = el.bounding_box()
            if not b:
                return False
            x, y = b["x"] + min(b["width"] / 2, 60), b["y"] + b["height"] / 2
            if view == "phone":
                page.touchscreen.tap(x, y)
            else:
                move(x, y); page.wait_for_timeout(250); page.mouse.down(); page.mouse.up()
            return True

        def scroll(dy, times=3):
            for _ in range(times):
                if view == "phone":
                    x, y0 = W * 0.55, H * 0.72
                    pts = [(x, y0 - dy * k / 10) for k in range(11)]
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": pts[0][0], "y": pts[0][1]}]})
                    for px, py in pts[1:]:
                        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": px, "y": py}]})
                        page.wait_for_timeout(16)
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                else:
                    move(W * 0.45, H * 0.55, steps=8)
                    for _ in range(8):
                        page.mouse.wheel(0, dy / 8); page.wait_for_timeout(30)
                page.wait_for_timeout(700)

        try:
            qs = [question] if isinstance(question, str) else list(question)
            for qi, q in enumerate(qs):
                for name in providers:
                    prov = provs[name]
                    page.goto(prov["home"], wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(1500)
                    mark("open", f"فتحت صفحة البحث ({name}).", f"Opened the search page ({name}).", page.url)
                    if _robot(page):
                        fx.robot_checks.append(name)
                        mark("robot", "فحص «لست روبوتاً»: توقفت ولن أتجاوزه.", "A robot check: I stopped and did not get past it.", page.url)
                        page.wait_for_timeout(1500)
                        continue
                    box = page.locator(prov["box"]).first
                    try:
                        box.wait_for(state="visible", timeout=8000)
                    except Exception:
                        mark("skip", "لم أجد خانة البحث.", "No search box found.", page.url)
                        continue
                    press_on(box)
                    page.wait_for_timeout(400)
                    mark("type", "أكتب السؤال كما يكتبه المقيم.", "Typing the question the way a resident does.", page.url)
                    page.keyboard.type(q, delay=type_delay_ms)  # typing only ever happens here, in the search box
                    page.wait_for_timeout(500)
                    page.keyboard.press("Enter")
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2200)
                    if _robot(page):
                        fx.robot_checks.append(name)
                        mark("robot", "فحص «لست روبوتاً» بعد البحث: توقفت ولن أتجاوزه.", "A robot check after the search: I stopped and did not get past it.", page.url)
                        page.wait_for_timeout(1500)
                        continue
                    fx.provider = name
                    mark("search", "النتائج كما يراها المقيم.", "The results, as a resident sees them.", page.url)
                    scroll(H * 0.5, times=3)
                    mark("scroll", "أقرأ النتائج إلى أسفل.", "Reading down the results.", page.url)
                    if qi < len(qs) - 1:
                        break  # an overview: the next question; only the last one opens an official page
                    links = page.locator(prov["results"])
                    target = None
                    for i in range(min(links.count(), 60)):
                        href = links.nth(i).evaluate("a => a.href") or ""
                        if any(o in _host(href) for o in OWN_HOSTS) or not links.nth(i).is_visible():
                            continue
                        if href.startswith("http") and official(href) and not check_url(href, _cache=cache) and not href.startswith(own or ("\0",)):
                            target = links.nth(i); break
                    if target is None:
                        mark("skip", "لا نتيجة رسمية لأفتحها. لا أفتح غير الرسمية.", "No official result to open. I never open one that is not official.", page.url)
                        break
                    scroll(-H * 0.4, times=1)
                    mark("click", "أفتح النتيجة الرسمية فقط.", "Opening the official result only.", target.evaluate("a => a.href") or "")
                    with page.expect_navigation(timeout=20000, wait_until="domcontentloaded"):
                        press_on(target)
                    page.wait_for_timeout(2500)
                    if not official(page.url):
                        mark("left", "وصلت خارج السجل فغادرت فوراً.", "Landed off the register, so I left at once.", page.url)
                        page.go_back(timeout=15000)
                        break
                    fx.opened = _host(page.url)
                    mark("open", f"الصفحة الرسمية: {fx.opened}.", f"The official page: {fx.opened}.", page.url)
                    scroll(H * 0.55, times=3)
                    mark("done", "انتهيت. الرمادية بقيت مغلقة.", "Done. Grey results stayed closed.", page.url)
                    page.wait_for_timeout(1200)
                    break
        except Exception as e:  # a failed recording is a fact for the desk, not a crash
            fx.error = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        finally:
            page.wait_for_timeout(300)
            cast.stop()
            ctx.close()
            browser.close()
            fx.video = str(frames)
            if cast.times:  # moments are timed from the first recorded frame, so captions line up with the video
                lag = int((cast.times[0] - t0_wall) * 1000)
                for m in fx.moments:
                    m.t_ms = max(0, m.t_ms - lag)
    return fx


class Screencast:
    """Chromium's screencast at device resolution: every changed frame saved as a JPEG with its time."""

    def __init__(self, cdp, folder: Path, size: dict, quality: int = 92):
        self.cdp, self.folder, self.size, self.quality = cdp, Path(folder), size, quality
        self.folder.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self.times: list[float] = []

    def _frame(self, ev):
        import base64
        self.n += 1
        (self.folder / f"{self.n:05d}.jpg").write_bytes(base64.b64decode(ev["data"]))
        self.times.append(float(ev["metadata"].get("timestamp") or time.time()))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception:
            pass

    def start(self):
        self.cdp.on("Page.screencastFrame", self._frame)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": self.quality, "everyNthFrame": 1,
                                               "maxWidth": self.size["width"], "maxHeight": self.size["height"]})

    def stop(self):
        try:
            self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        lines = []
        for i, t in enumerate(self.times):
            nxt = self.times[i + 1] if i + 1 < len(self.times) else t + 1.0
            lines.append(f"file '{i + 1:05d}.jpg'\nduration {max(0.001, nxt - t):.4f}")
        if lines:
            lines.append(f"file '{len(self.times):05d}.jpg'")
        (self.folder / "frames.txt").write_text("\n".join(lines) + "\n")


def speed_up(src: str | Path, dst: str | Path, factor: float = 3.0, crf: int = 26, max_width: int | None = None) -> Path:
    """A sped-up H.264 MP4 (no audio) of a recording folder made by ``record_search``, ready to stream."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    vf = f"setpts=PTS/{factor},fps=30"
    if max_width:
        vf += f",scale='min({max_width},iw)':-2:flags=lanczos"
    vf += ",scale=trunc(iw/2)*2:trunc(ih/2)*2"
    dst = Path(dst)
    src = Path(src)
    inp = ["-f", "concat", "-safe", "0", "-i", str(src / "frames.txt")] if src.is_dir() else ["-i", str(src)]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inp, "-vf", vf, "-an", "-c:v", "libx264",
                    "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
                   check=True)
    return dst
