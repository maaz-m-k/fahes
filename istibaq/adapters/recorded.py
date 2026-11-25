"""Recorded fakes: an ``httpx.Client`` that replays tests/fixtures/recorded/.

Use ``recorded_client()`` in any test (watch, service, feeds) to run every
adapter offline. Fakes were written by hand from each service's documented
response shape and use only reserved names (``.test``, ``.example``).
Requests carrying a key are accepted, but the key is never stored.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import httpx

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "recorded"


def recorded_client(fixtures: Path | str | None = None, log: list | None = None) -> httpx.Client:
    root = Path(fixtures or DEFAULT_DIR)

    def load(name: str):
        return json.loads((root / name).read_text(encoding="utf-8"))

    sth = itertools.cycle(load("ct_sth.json"))

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if log is not None:
            log.append(f"{request.method} {host}{path}")
        if host == "api.dataforseo.com":
            if path == "/v3/appendix/user_data":
                return httpx.Response(200, json=load("dataforseo_user_data.json"))
            if path.endswith("/task_post"):
                return httpx.Response(200, json=load("dataforseo_task_post.json"))
            if path.endswith("/tasks_ready"):
                return httpx.Response(200, json=load("dataforseo_tasks_ready.json"))
            if "/task_get/advanced/" in path:
                return httpx.Response(200, json=load("dataforseo_task_get_advanced.json"))
        if host == "api.search.brave.com":
            return httpx.Response(200, json=load("brave.json"))
        if host == "places.googleapis.com":
            return httpx.Response(200, json=load("places.json"))
        if host == "rdap.org":
            return httpx.Response(200, json=load("rdap.json"))
        if path.endswith("/ct/v1/get-sth"):
            return httpx.Response(200, json=next(sth))
        if host == "crt.sh":
            q = request.url.params.get("q", "").replace("%", "").strip(".").lower()
            rows = [r for r in load("crtsh.json") if not q or q in r["name_value"]]
            return httpx.Response(200, json=rows)
        if host == "www.whoisds.com":
            return httpx.Response(200, content=(root / "nrd.txt").read_bytes())
        if host == "openrouter.ai":
            return httpx.Response(200, json=load("openrouter.json"))
        return httpx.Response(404, json={"error": "no recorded fake"})

    return httpx.Client(transport=httpx.MockTransport(handler))
