"""Per-model token prices for turn cost accounting (USD per million tokens)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Keyed by model-id prefix, so dated snapshots (claude-haiku-4-5-20251001) match.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}
# An unpriced model is charged at the most expensive known rate, so cost is never understated.
_FALLBACK = max(_PRICES_PER_MTOK.values())


def price_per_mtok(model: str) -> tuple[float, float]:
    """(input, output) USD per million tokens for `model`."""
    for prefix, price in _PRICES_PER_MTOK.items():
        if model.startswith(prefix):
            return price
    logger.warning("No price for model %r; charging %s per million tokens", model, _FALLBACK)
    return _FALLBACK


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = price_per_mtok(model)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
