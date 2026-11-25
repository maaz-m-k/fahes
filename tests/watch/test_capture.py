"""Two-view capture against a local test server on 127.0.0.1 only."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright")
from istibaq.capture import CaptureRefused, capture  # noqa: E402
from istibaq.capture.twoview import check_url  # noqa: E402

PAGES = {
    "/benign": "<html><head><title>Garden tips</title></head><body><p>How to grow tomatoes on a balcony in "
               "winter. Water twice a week and keep them in the sun.</p></body></html>",
    "/fake": "<html><head><title>TAMM - Pay traffic fine</title></head><body><h1>TAMM</h1><p>Pay your Abu Dhabi "
             "Police fine now. Transfer to IBAN AE070331234567890123456.</p><form><input name=card></form></body></html>",
    "/wall": "<html><head><title>Just a moment...</title></head><body><div class='cf-turnstile'></div>"
             "Verify you are human</body></html>",
    "/final": "<html><head><title>Final</title></head><body>Final page</body></html>",
    "/meta": "<html><head><meta http-equiv='refresh' content='0;url=/final'><title>wait</title></head><body>wait</body></html>",
}


class Handler(BaseHTTPRequestHandler):
    posts = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        Handler.posts += 1
        self.send_response(400)
        self.end_headers()

    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        path = self.path
        if path == "/cloak":
            path = "/fake" if ("iPhone" in ua or "Mobile" in ua) else "/benign"
        if path == "/slow-for-server":
            if "iPhone" not in ua:
                time.sleep(4)
            path = "/benign"
        if path == "/bilingual":
            path = "/benign"
        if path == "/escape":
            return self._redirect("http://escape.example/")
        if path == "/r1":
            return self._redirect("/r2")
        if path == "/r2":
            return self._redirect("/meta")
        body = PAGES.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def _redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setenv("ISTIBAQ_CAPTURE_LOCAL_ONLY", "1")


def test_cloaking_is_exposed_by_the_two_views(server, tmp_path):
    cap = capture(server + "/cloak", tmp_path, settle_ms=300)
    assert cap.server.title == "Garden tips" and cap.phone.title.startswith("TAMM")
    assert cap.facts.two_view_difference and "different title" in cap.facts.two_view_difference
    assert cap.facts.live_page_brand == "TAMM"
    assert cap.facts.payee == "AE070331234567890123456"
    assert any(n.startswith("hidden from server") for n in cap.saw_through)
    assert cap.server.screenshots and cap.phone.screenshots
    assert all(len(s.sha256) == 64 for s in cap.phone.screenshots)
    assert Handler.posts == 0  # never submits anything


def test_redirect_chain_is_recorded_hop_by_hop(server, tmp_path):
    cap = capture(server + "/r1", tmp_path, settle_ms=1500)
    chain = [u.removeprefix(server) for u in cap.facts.redirect_chain]
    assert chain == ["/r1", "/r2", "/meta", "/final"]
    assert [h.kind for h in cap.phone.hops] == ["http", "http", "http", "final"] or cap.phone.hops[-1].kind == "final"
    assert any("redirect chain followed" in n for n in cap.saw_through)


def test_human_check_wall_is_detected_not_solved(server, tmp_path):
    cap = capture(server + "/wall", tmp_path, settle_ms=300)
    assert cap.facts.human_check_wall is True
    assert any("not solved" in n for n in cap.saw_through)


def test_dead_link_is_a_fact_not_a_crash(server, tmp_path):
    cap = capture("http://127.0.0.1:9/", tmp_path, timeout_ms=3000, settle_ms=200)
    assert cap.server.error and cap.phone.error


def test_local_only_guard_refuses_real_addresses(tmp_path):
    with pytest.raises(CaptureRefused):
        capture("https://suspect.example/", tmp_path)


def test_a_view_that_times_out_is_a_fact_not_a_difference(server, tmp_path):
    cap = capture(server + "/slow-for-server", tmp_path, timeout_ms=1500, settle_ms=200)
    assert cap.server.error and not cap.phone.error
    assert cap.differences == [] and cap.facts.two_view_difference is None
    assert cap.failures and cap.failures[0].startswith("server view did not load")
    assert {"facts", "server", "phone", "differences"} <= set(cap.to_dict())


def test_same_content_in_both_views_is_not_cloaking(server, tmp_path):
    cap = capture(server + "/bilingual", tmp_path, settle_ms=200)
    assert cap.differences == [] and cap.facts.two_view_difference is None


def test_redirect_to_a_non_local_address_is_blocked_in_local_only_mode(server, tmp_path):
    cap = capture(server + "/escape", tmp_path, settle_ms=200)
    assert "escape.example" not in cap.phone.final_url
    assert "Refused" in cap.phone.error or "refused" in cap.phone.error


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/", "javascript:alert(1)"])
def test_only_http_and_https(url, tmp_path):
    with pytest.raises(CaptureRefused):
        capture(url, tmp_path)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080/", "http://localhost/", "http://10.0.0.5/",
                                 "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://192.168.1.1/",
                                 "http://[fdaa::3]/"])
def test_non_public_addresses_refused_outside_local_only(url):
    assert check_url(url, local_only=False) == "non-public address"


def test_public_address_allowed_outside_local_only():
    assert check_url("http://93.184.215.14/", local_only=False) is None


@pytest.mark.parametrize("url", ["http://x:99999/", "http://[bad/"])
def test_malformed_address_is_refused_not_raised(url):
    why = check_url(url, local_only=False)
    assert why and why.startswith("malformed address")


def test_screenshots_are_sharp_pngs_with_matching_hashes(server, tmp_path):
    import hashlib
    import struct
    from pathlib import Path
    cap = capture(server + "/benign", tmp_path, settle_ms=200)
    for view, scale in ((cap.server, 2), (cap.phone, 3)):
        shot = view.screenshots[0]
        data = Path(shot.path).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        css_width = 1280 if view.name == "server" else 390  # iPhone 13 viewport
        assert width == css_width * scale
        assert hashlib.sha256(data).hexdigest() == shot.sha256
