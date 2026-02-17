"""Tests for CostCalculator."""

from __future__ import annotations

import pytest

from resume_tailor.logging.cost_calculator import (
    MODEL_PRICING,
    TAVILY_COST_PER_SEARCH,
    calculate_cost,
)


class TestCostCalculator:
    def test_haiku_cost(self):
        # 1M input + 1M output for Haiku: $0.80 + $4.00 = $4.80
        cost = calculate_cost([("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)])
        assert cost == pytest.approx(4.80)

    def test_sonnet_cost(self):
        # 1M input + 1M output for Sonnet: $3.00 + $15.00 = $18.00
        cost = calculate_cost([("claude-sonnet-4-5-20250929", 1_000_000, 1_000_000)])
        assert cost == pytest.approx(18.00)

    def test_small_token_count(self):
        # 500 input + 200 output for Haiku
        cost = calculate_cost([("claude-haiku-4-5-20251001", 500, 200)])
        expected = (500 / 1_000_000) * 0.80 + (200 / 1_000_000) * 4.00
        assert cost == pytest.approx(expected)

    def test_multiple_calls(self):
        calls = [
            ("claude-haiku-4-5-20251001", 1000, 500),
            ("claude-sonnet-4-5-20250929", 2000, 1000),
            ("claude-haiku-4-5-20251001", 800, 300),
        ]
        expected = (
            (1000 / 1e6) * 0.80 + (500 / 1e6) * 4.00
            + (2000 / 1e6) * 3.00 + (1000 / 1e6) * 15.00
            + (800 / 1e6) * 0.80 + (300 / 1e6) * 4.00
        )
        assert calculate_cost(calls) == pytest.approx(expected)

    def test_tavily_search_cost(self):
        cost = calculate_cost([], search_count=5)
        assert cost == pytest.approx(0.05)

    def test_combined_cost(self):
        calls = [("claude-haiku-4-5-20251001", 10000, 5000)]
        cost = calculate_cost(calls, search_count=3)
        expected = (
            (10000 / 1e6) * 0.80 + (5000 / 1e6) * 4.00
            + 3 * 0.01
        )
        assert cost == pytest.approx(expected)

    def test_unknown_model_ignored(self):
        cost = calculate_cost([("unknown-model", 1000, 1000)])
        assert cost == 0.0

    def test_empty_calls(self):
        assert calculate_cost([]) == 0.0

    def test_zero_tokens(self):
        cost = calculate_cost([("claude-haiku-4-5-20251001", 0, 0)])
        assert cost == 0.0

    def test_zero_search(self):
        cost = calculate_cost([], search_count=0)
        assert cost == 0.0

    def test_pricing_constants(self):
        assert "claude-haiku-4-5-20251001" in MODEL_PRICING
        assert "claude-sonnet-4-5-20250929" in MODEL_PRICING
        assert TAVILY_COST_PER_SEARCH == 0.01
