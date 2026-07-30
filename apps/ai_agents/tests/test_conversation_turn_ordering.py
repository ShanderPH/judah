"""Regression tests for deterministic HubSpot message ordering."""

from __future__ import annotations

from itertools import permutations

from apps.ai_agents.services.conversation_turn import (
    current_incoming_turn,
    latest_incoming_message_id,
    normalize_conversation_history,
)


def test_provider_order_permutations_produce_the_same_current_turn() -> None:
    messages = [
        {
            "id": "outgoing-1",
            "direction": "OUTGOING",
            "text": "Como posso ajudar?",
            "created_at": "2026-07-28T12:00:00Z",
        },
        {
            "id": "incoming-1",
            "direction": "INCOMING",
            "text": "Primeira parte",
            "created_at": "2026-07-28T12:01:00Z",
        },
        {
            "id": "incoming-2",
            "direction": "INCOMING",
            "text": "Segunda parte",
            "created_at": "2026-07-28T12:02:00Z",
        },
    ]

    for provider_order in permutations(messages):
        context = {"conversation_history": list(provider_order)}
        assert [message["id"] for message in current_incoming_turn(context)] == [
            "incoming-1",
            "incoming-2",
        ]
        assert latest_incoming_message_id(context) == "incoming-2"


def test_missing_timestamp_never_overrides_a_dated_latest_message() -> None:
    history = normalize_conversation_history(
        [
            {"id": "dated", "direction": "INCOMING", "text": "Atual", "created_at": 1785240123000},
            {"id": "missing", "direction": "OUTGOING", "text": "Legado", "created_at": None},
        ]
    )

    assert [message["id"] for message in history] == ["missing", "dated"]
    assert latest_incoming_message_id({"conversation_history": history}) == "dated"


def test_equal_timestamps_use_message_id_as_deterministic_tie_break() -> None:
    messages = [
        {"id": "b", "direction": "INCOMING", "text": "B", "created_at": "2026-07-28T12:00:00Z"},
        {"id": "a", "direction": "INCOMING", "text": "A", "created_at": "2026-07-28T12:00:00Z"},
    ]

    assert [message["id"] for message in normalize_conversation_history(messages)] == ["a", "b"]
