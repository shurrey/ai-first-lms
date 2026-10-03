"""Outbound HTTP clients that verify TLS against the OS trust store.

All outbound HTTPS (Anthropic, Fish Audio) should be built here. Set
TLS_INSECURE_SKIP_VERIFY=true only as an emergency escape hatch; it is honored
by these helpers alone and log_tls_mode() reports it as an ERROR.
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Any

import anthropic
import httpx
import truststore

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def insecure_skip_verify() -> bool:
    """True when TLS_INSECURE_SKIP_VERIFY is set to a truthy value (default false)."""
    return os.environ.get("TLS_INSECURE_SKIP_VERIFY", "false").strip().lower() in _TRUTHY


def tls_verify() -> ssl.SSLContext | bool:
    """httpx ``verify`` value: a truststore context, or False under the escape hatch."""
    if insecure_skip_verify():
        return False
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def make_http_client(**kw: Any) -> httpx.AsyncClient:
    """Async httpx client verifying via the OS trust store; ``kw`` is forwarded minus ``verify``."""
    kw.pop("verify", None)
    return httpx.AsyncClient(verify=tls_verify(), **kw)


def make_sync_http_client(**kw: Any) -> httpx.Client:
    """Sync counterpart of make_http_client, for SDKs that only accept httpx.Client."""
    kw.pop("verify", None)
    return httpx.Client(verify=tls_verify(), **kw)


async def log_anthropic_request(request: httpx.Request) -> None:
    """One INFO line per outbound model request, retries included, so spend can be counted
    from the logs."""
    logger.info("anthropic_request %s %s", request.method, request.url.path)


def make_anthropic_client(**kw: Any) -> anthropic.AsyncAnthropic:
    """AsyncAnthropic backed by make_http_client(); ``kw`` goes to the Anthropic constructor.

    A caller-supplied ``http_client`` is used as-is, so it must do its own TLS verification.
    """
    http_client = kw.pop("http_client", None) or make_http_client(
        event_hooks={"request": [log_anthropic_request]})
    return anthropic.AsyncAnthropic(http_client=http_client, **kw)


def log_tls_mode() -> None:
    """Log the outbound TLS mode; call once at process startup."""
    if insecure_skip_verify():
        logger.error(
            "TLS_INSECURE_SKIP_VERIFY is enabled: outbound TLS certificates are NOT verified"
        )
    else:
        logger.info("Outbound TLS verification uses the OS trust store (truststore)")
