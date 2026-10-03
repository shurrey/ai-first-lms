from __future__ import annotations

import logging
import ssl
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import truststore

from engine import http as engine_http

SRC_DIR = Path(__file__).resolve().parents[2]
# Built by concatenation so this file does not match its own grep.
FORBIDDEN = "verify=" + "False"


@pytest.fixture(autouse=True)
def _clear_escape_hatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TLS_INSECURE_SKIP_VERIFY", raising=False)


def test_escape_hatch_off_by_default() -> None:
    assert engine_http.insecure_skip_verify() is False


def test_tls_verify_is_truststore_context() -> None:
    ctx = engine_http.tls_verify()
    assert isinstance(ctx, truststore.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_make_http_client_passes_truststore_context() -> None:
    with patch("common.http.httpx.AsyncClient") as client_cls:
        engine_http.make_http_client(timeout=5)
    kwargs = client_cls.call_args.kwargs
    assert isinstance(kwargs["verify"], truststore.SSLContext)
    assert kwargs["timeout"] == 5


def test_make_http_client_ignores_caller_verify() -> None:
    with patch("common.http.httpx.AsyncClient") as client_cls:
        engine_http.make_http_client(**{"verify": False})
    assert isinstance(client_cls.call_args.kwargs["verify"], truststore.SSLContext)


def test_make_sync_http_client_passes_truststore_context() -> None:
    with patch("common.http.httpx.Client") as client_cls:
        engine_http.make_sync_http_client(base_url="https://example.invalid")
    kwargs = client_cls.call_args.kwargs
    assert isinstance(kwargs["verify"], truststore.SSLContext)
    assert kwargs["base_url"] == "https://example.invalid"


def test_make_anthropic_client_uses_helper_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    helper_client = httpx.AsyncClient()
    with patch("common.http.make_http_client", return_value=helper_client) as factory:
        client = engine_http.make_anthropic_client()
    factory.assert_called_once()
    assert client._client is helper_client


async def test_anthropic_client_logs_each_outbound_request(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = engine_http.make_anthropic_client()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    with caplog.at_level(logging.INFO, logger="common.http"):
        for hook in client._client.event_hooks["request"]:
            await hook(request)

    assert [r.getMessage() for r in caplog.records] == ["anthropic_request POST /v1/messages"]


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
def test_escape_hatch_disables_verification(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TLS_INSECURE_SKIP_VERIFY", value)
    assert engine_http.insecure_skip_verify() is True
    assert engine_http.tls_verify() is False
    with patch("common.http.httpx.AsyncClient") as client_cls:
        engine_http.make_http_client()
    assert client_cls.call_args.kwargs["verify"] is False


def test_log_tls_mode_errors_when_escape_hatch_enabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("TLS_INSECURE_SKIP_VERIFY", "true")
    with caplog.at_level(logging.INFO, logger="common.http"):
        engine_http.log_tls_mode()
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "TLS_INSECURE_SKIP_VERIFY" in errors[0].getMessage()


def test_log_tls_mode_no_error_by_default(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="common.http"):
        engine_http.log_tls_mode()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_create_app_logs_tls_mode(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from engine.app import create_app

    monkeypatch.setenv("TLS_INSECURE_SKIP_VERIFY", "true")
    with caplog.at_level(logging.INFO, logger="common.http"):
        create_app()
    assert any(r.levelno == logging.ERROR for r in caplog.records)


_SKIP_DIRS = {"node_modules", ".next", "__pycache__", ".venv"}


def test_no_disabled_tls_verification_in_src() -> None:
    needle = FORBIDDEN.encode()
    offenders = [
        str(path.relative_to(SRC_DIR.parent))
        for path in SRC_DIR.rglob("*")
        if path.is_file()
        and not _SKIP_DIRS.intersection(path.parts)
        and needle in path.read_bytes()
    ]
    assert offenders == []
