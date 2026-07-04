"""Rough token pricing for AI-run cost estimates.

Prices are approximate USD per 1M tokens (input, output) and WILL drift; treat
the estimate as a ballpark, not a bill. Matched by model-id substring, most
specific entries first.
"""

from __future__ import annotations

from graider.models import Usage

_PRICES: list[tuple[str, float, float]] = [
    ("claude-opus", 15.0, 75.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-haiku", 0.80, 4.0),
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.0),
    ("gpt-4.1-mini", 0.40, 1.60),
    ("gpt-4.1", 2.0, 8.0),
    ("gemini-1.5-flash", 0.075, 0.30),
    ("gemini-2.0-flash", 0.10, 0.40),
    ("gemini-1.5-pro", 1.25, 5.0),
    ("gemini", 0.30, 1.20),
    ("glm-4", 0.60, 0.60),
]


def estimate_cost(model: str, usage: Usage) -> float | None:
    """Best-effort USD estimate for a run, or None if the model is unknown."""
    for key, price_in, price_out in _PRICES:
        if key in model:
            return usage.input_tokens / 1e6 * price_in + usage.output_tokens / 1e6 * price_out
    return None
