"""Deterministic AI rollout cohort tests."""

from django.test import override_settings

from apps.ai_agents.services.rollout import is_ai_rollout_enabled


@override_settings(AI_ROUTING_ROLLOUT_PERCENTAGE=0)
def test_zero_percent_disables_ai_for_every_identifier() -> None:
    assert is_ai_rollout_enabled("ticket-1") is False


@override_settings(AI_ROUTING_ROLLOUT_PERCENTAGE=100)
def test_full_rollout_enables_ai_for_every_identifier() -> None:
    assert is_ai_rollout_enabled("ticket-1") is True


@override_settings(AI_ROUTING_ROLLOUT_PERCENTAGE=25)
def test_partial_rollout_is_stable_for_same_identifier() -> None:
    first = is_ai_rollout_enabled("ticket-stable")
    assert is_ai_rollout_enabled("ticket-stable") is first
