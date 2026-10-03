"""Engine-facing outbound HTTP helpers; the Anthropic client honours LLM_FIXTURE_MODE."""

from __future__ import annotations

from typing import Any

import anthropic

from common import http as common_http
from common.http import (
    insecure_skip_verify,
    log_tls_mode,
    make_http_client,
    make_sync_http_client,
    tls_verify,
)
from engine.llm_fixture import CALLING_MODES, FixtureAnthropicClient, fixture_dir, fixture_mode

__all__ = [
    "insecure_skip_verify",
    "log_tls_mode",
    "make_anthropic_client",
    "make_http_client",
    "make_sync_http_client",
    "tls_verify",
]


def make_anthropic_client(**kw: Any) -> anthropic.AsyncAnthropic | FixtureAnthropicClient:
    """The real client, or a fixture client under LLM_FIXTURE_MODE=record|replay|fill.

    Replay never builds the real client, so it needs no API key.
    """
    mode = fixture_mode()
    if mode == "off":
        return common_http.make_anthropic_client(**kw)
    upstream = common_http.make_anthropic_client(**kw) if mode in CALLING_MODES else None
    return FixtureAnthropicClient(mode, fixture_dir(), upstream)
