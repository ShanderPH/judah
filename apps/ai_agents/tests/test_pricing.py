"""Unit tests for the token-pricing calculator (pure, no DB, no network)."""

from __future__ import annotations

from decimal import Decimal

from apps.ai_agents.utils.pricing import PRICING_PER_MILLION_TOKENS, calculate_cost


class TestCalculateCost:
    def test_gpt55_baseline(self) -> None:
        cost = calculate_cost("gpt-5.5", 1_000_000, 1_000_000)
        assert cost == 35.0

    def test_gpt4o_mini_baseline(self) -> None:
        # 1M input + 1M output = $0.15 + $0.60 = $0.75.
        cost = calculate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == 0.75

    def test_gpt4o_baseline(self) -> None:
        cost = calculate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert cost == 20.0

    def test_dated_variant_normalized_to_canonical(self) -> None:
        # Dated release variants should map to the canonical base model.
        cost_dated = calculate_cost("gpt-4o-2024-08-06", 1_000_000, 0)
        cost_base = calculate_cost("gpt-4o", 1_000_000, 0)
        assert cost_dated == cost_base

    def test_mini_dated_variant_normalized(self) -> None:
        cost_dated = calculate_cost("gpt-4o-mini-2024-07-18", 1_000_000, 0)
        cost_base = calculate_cost("gpt-4o-mini", 1_000_000, 0)
        assert cost_dated == cost_base

    def test_unknown_model_returns_zero(self) -> None:
        assert calculate_cost("unknown-model", 1000, 1000) == 0.0

    def test_empty_model_returns_zero(self) -> None:
        assert calculate_cost("", 1000, 1000) == 0.0

    def test_zero_tokens_returns_zero(self) -> None:
        assert calculate_cost("gpt-4o", 0, 0) == 0.0

    def test_only_input_tokens_counted(self) -> None:
        cost = calculate_cost("gpt-4o-mini", 1_000_000, 0)
        assert cost == 0.15

    def test_only_output_tokens_counted(self) -> None:
        cost = calculate_cost("gpt-4o-mini", 0, 1_000_000)
        assert cost == 0.60

    def test_case_insensitive_model_name(self) -> None:
        assert calculate_cost("GPT-4O", 1_000_000, 0) == calculate_cost("gpt-4o", 1_000_000, 0)


class TestPricingTable:
    def test_has_canonical_models(self) -> None:
        assert "gpt-5.5" in PRICING_PER_MILLION_TOKENS
        assert "gpt-4o" in PRICING_PER_MILLION_TOKENS
        assert "gpt-4o-mini" in PRICING_PER_MILLION_TOKENS

    def test_prices_are_decimals(self) -> None:
        for model_prices in PRICING_PER_MILLION_TOKENS.values():
            assert isinstance(model_prices["input"], Decimal)
            assert isinstance(model_prices["output"], Decimal)

    def test_output_costs_more_than_input(self) -> None:
        for model_prices in PRICING_PER_MILLION_TOKENS.values():
            assert model_prices["output"] >= model_prices["input"]
