from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def event_loop_policy():
    """Use the default event loop policy for module-scoped async fixtures."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()
