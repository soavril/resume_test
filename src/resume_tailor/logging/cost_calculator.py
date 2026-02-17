"""Cost calculator for Claude API and Tavily search usage."""

from __future__ import annotations

# Pricing per 1M tokens (USD)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}

TAVILY_COST_PER_SEARCH = 0.01


def calculate_cost(
    calls: list[tuple[str, int, int]],
    search_count: int = 0,
) -> float:
    """Calculate total cost for a set of API calls and searches.

    Args:
        calls: List of (model_id, input_tokens, output_tokens) tuples.
        search_count: Number of Tavily search API calls.

    Returns:
        Total estimated cost in USD.
    """
    total = 0.0
    for model_id, input_tokens, output_tokens in calls:
        pricing = MODEL_PRICING.get(model_id)
        if pricing is None:
            continue
        total += (input_tokens / 1_000_000) * pricing["input"]
        total += (output_tokens / 1_000_000) * pricing["output"]
    total += search_count * TAVILY_COST_PER_SEARCH
    return total
