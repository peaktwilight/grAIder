from graider.models import Usage
from graider.pricing import estimate_cost


def test_estimate_cost_known_model():
    cost = estimate_cost("claude-opus-4-8", Usage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost == 15.0 + 75.0


def test_estimate_cost_unknown_model_is_none():
    assert estimate_cost("mystery-model", Usage(input_tokens=10, output_tokens=10)) is None
