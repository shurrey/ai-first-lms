"""MCP servers read "now" from common.clock (LMS_AS_OF)."""
from __future__ import annotations

import pytest

from data_mcp.mcp_base import create_mcp_server


def test_server_creation_fails_fast_on_malformed_as_of(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LMS_AS_OF", "mid-October")
    with pytest.raises(ValueError, match="LMS_AS_OF"):
        create_mcp_server("roster", [])


def test_server_creation_accepts_unset_as_of(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("LMS_AS_OF", raising=False)
    create_mcp_server("roster", [])
