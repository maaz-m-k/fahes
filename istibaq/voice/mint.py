"""Mint short-lived OpenAI Realtime client secrets; the real key never leaves the server.

Uses ``POST https://api.openai.com/v1/realtime/client_secrets`` (GA Realtime API), with the
session settings fixed here, server-side. The browser only ever receives the ephemeral value.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

import httpx

URL = "https://api.openai.com/v1/realtime/client_secrets"
MODEL = os.environ.get("ISTIBAQ_REALTIME_MODEL", "gpt-realtime-2.1")  # session.json names the same default
FALLBACK_MODEL = os.environ.get("ISTIBAQ_REALTIME_FALLBACK", "gpt-realtime-2.1-mini")
TTL_SECONDS = 600
# Estimate logged at mint: a typical 10-minute desk session of realtime audio, in USD.
# Real usage is billed per audio token; this is an estimate until usage events are metered.
SESSION_USD_ESTIMATE = float(os.environ.get("ISTIBAQ_REALTIME_SESSION_USD", "0.50"))

# One source for the session, shared with the screens (web/src/voice/toolSpec.ts reads the same file).
SESSION = json.loads((Path(__file__).with_name("session.json")).read_text(encoding="utf-8"))
INSTRUCTIONS: str = SESSION["instructions"]
VOICE: str = SESSION["voice"]
TOOL_NAMES = [t["name"] for t in SESSION["tools"]]


def _tools() -> list[dict]:
    return [dict(t) for t in SESSION["tools"]]


def session_config(model: str) -> dict:
    return {"type": "realtime", "model": model, "instructions": INSTRUCTIONS, "tools": _tools(),
            "tool_choice": "auto", "max_output_tokens": 400,
            "audio": {"input": {"turn_detection": {"type": "semantic_vad", "eagerness": "auto", "create_response": True,
                                                   "interrupt_response": True},
                                "transcription": {"model": "gpt-4o-mini-transcribe"}},
                      "output": {"voice": VOICE}}}


class VoiceUnavailable(Exception):
    pass


def mint(cost_sink: Callable[[str, float, dict], None] | None = None,
         transport: httpx.BaseTransport | None = None) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise VoiceUnavailable("OPENAI_API_KEY not set")
    last_status = None
    with httpx.Client(transport=transport, timeout=15) as client:
        for model in (MODEL, FALLBACK_MODEL):
            resp = client.post(URL, headers={"Authorization": f"Bearer {key}"},
                               json={"expires_after": {"anchor": "created_at", "seconds": TTL_SECONDS},
                                     "session": session_config(model)})
            last_status = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                value = data.get("value") or (data.get("client_secret") or {}).get("value")
                if not value or value == key:
                    raise VoiceUnavailable("unexpected mint response")
                if cost_sink:
                    cost_sink("openai_realtime", SESSION_USD_ESTIMATE,
                              {"event": "mint", "model": model, "estimate": True, "minutes": TTL_SECONDS // 60})
                return {"client_secret": value, "expires_at": data.get("expires_at"), "model": model,
                        "tools": TOOL_NAMES}
    raise VoiceUnavailable(f"mint failed with HTTP {last_status}")
