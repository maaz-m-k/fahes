"""Real footage of the agent working, against a local search page and local pages on 127.0.0.1 only."""
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright")
from istibaq.capture import capture  # noqa: E402
from istibaq.capture.footage import record_search, speed_up  # noqa: E402
from istibaq.watch import Round, record_work  # noqa: E402
from istibaq.watch.questions import Question  # noqa: E402

HOME = ("<html><body style='font:20px sans-serif'><form action='/results'><input name='q' style='width:400px'>"
        "</form></body></html>")


class Handler(BaseHTTPRequestHandler):
    visited: list[str] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.visited.append(self.path)
        u = urlparse(self.path)
        if u.path == "/":
            body = HOME
        elif u.path == "/results":
            q = parse_qs(u.query).get("q", [""])[0]
            filler = "".join(f"<p>result text {i}</p>" for i in range(40))
            body = (f"<html><body><h1>{q}</h1><a href='/grey'>A typing office</a><br>"
                    f"<a href='/official'>The official page</a>{filler}</body></html>")
        elif u.path == "/cloak":
            ua = self.headers.get("User-Agent", "")
            body = ("<html><title>Pay fine</title><body><h1>Pay your fine (synthetic)</h1></body></html>"
                    if "iPhone" in ua else "<html><title>Garden</title><body>Garden tips</body></html>")
        else:
            body = "<html><body>" + "<p>page text</p>" * 60 + "</body></html>"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setenv("ISTIBAQ_CAPTURE_LOCAL_ONLY", "1")


@pytest.mark.parametrize("view", ["computer", "phone"])
def test_records_a_resident_search_and_opens_only_the_official_result(site, tmp_path, view):
    Handler.visited.clear()
    prov = {"local": {"home": site + "/", "box": "input[name=q]", "results": "a[href]"}}
    fx = record_search("pay traffic fine", tmp_path, view=view, providers=("local",), provider_urls=prov,
                       official=lambda u: u.rstrip("/").endswith("/official"), type_delay_ms=20)
    assert not fx.error, fx.error
    actions = [m.action for m in fx.moments]
    assert actions[:3] == ["open", "type", "search"] and "click" in actions and "done" in actions
    assert fx.opened == "127.0.0.1" and fx.provider == "local"
    assert "/official" in Handler.visited and "/grey" not in Handler.visited  # grey results stay closed
    frames = sorted(Path(fx.video).glob("*.jpg"))
    assert len(frames) > 5 and (Path(fx.video) / "frames.txt").exists()
    if view == "phone":
        assert (fx.width, fx.height) == (390 * 3, 664 * 3)  # sharp: device resolution, not CSS pixels
    if shutil.which("ffmpeg"):
        mp4 = speed_up(fx.video, tmp_path / f"{view}.mp4", 3)
        assert mp4.stat().st_size > 1000


def test_a_refused_address_is_never_opened(tmp_path):
    prov = {"far": {"home": "https://example.com/", "box": "input", "results": "a"}}
    fx = record_search("x", tmp_path, providers=("far",), provider_urls=prov)
    assert fx.provider == "" and not fx.opened


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_capture_can_record_both_views(site, tmp_path):
    cap = capture(site + "/cloak", tmp_path, record=True, settle_ms=500)
    assert cap.server.video.endswith("server.mp4") and Path(cap.server.video).exists()
    assert cap.phone.video.endswith("phone.mp4") and Path(cap.phone.video).exists()
    assert "Pay your fine" in cap.phone.text and "Garden" in cap.server.text


def test_record_work_makes_one_overview_per_view(tmp_path):
    class Fake:
        def __init__(self, qs, view):
            self.qs, self.view = qs, view

        def to_dict(self):
            return {"question": " | ".join(self.qs), "view": self.view, "provider": "fahes", "opened": "x.gov.ae",
                    "video": "", "robot_checks": []}

    rnd = Round("r1", "now")
    made = record_work(rnd, tmp_path, questions=[Question("t", "en", "q one"), Question("t", "en", "q two"),
                                                 Question("t", "en", "q three")],
                       limit=2, recorder=lambda qs, out, view: Fake(qs, view))
    assert [(m["question"], m["view"]) for m in made] == [("q one | q two", "computer"), ("q one | q two", "phone")]
    assert [s.action for s in rnd.steps] == ["record", "record"]
