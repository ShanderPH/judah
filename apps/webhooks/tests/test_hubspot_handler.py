"""Tests for the HubSpot event router in ``apps.webhooks.handlers.hubspot_handler``.

These exercise the dispatch logic without hitting real Celery workers: the
underlying Celery tasks are mocked so the tests focus on routing / property
extraction.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings

from apps.webhooks.handlers.hubspot_handler import (
    _handle_ticket_entered_closed,
    handle_hubspot_event,
)


def _event(event_type: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(event_type=event_type, payload=payload, pk=1)


class TestHandleHubspotEvent:
    def test_ticket_property_change_dispatches(self) -> None:
        event = _event(
            "ticket.propertyChange",
            {
                "objectId": "42",
                "propertyName": "hs_v2_date_entered_939275049",
                "propertyValue": "1699999999000",
            },
        )
        with patch("apps.support.tasks.task_matchmaker_assign_single.delay") as mock_delay:
            handle_hubspot_event(event)
        mock_delay.assert_called_once()

    def test_owner_change_dispatches_owner_task(self) -> None:
        event = _event(
            "ticket.propertyChange",
            {"objectId": "42", "propertyName": "hubspot_owner_id", "propertyValue": "72733895"},
        )
        with patch("apps.support.tasks.task_handle_owner_change.delay") as mock_delay:
            handle_hubspot_event(event)
        mock_delay.assert_called_once()

    def test_contact_event_routed_to_contact_handler(self) -> None:
        event = _event("contact.propertyChange", {"objectId": "99"})
        # Just verify no exception: the handler logs by default when there is
        # nothing else to do.
        handle_hubspot_event(event)

    def test_deal_event_logs_only(self) -> None:
        event = _event("deal.creation", {"objectId": "1"})
        handle_hubspot_event(event)

    def test_conversation_event_routed(self) -> None:
        event = _event("conversation.newMessage", {"objectId": "77"})
        handle_hubspot_event(event)

    @override_settings(
        AI_ROUTING_ENABLED=True,
        SALOMAO_V1_BASE_URL="https://salomao.local",
        HUBSPOT_AI_REPLY_DISABLED_CHANNELS="whatsapp",
    )
    def test_whatsapp_conversation_dispatches_ai_pipeline(self) -> None:
        event = _event(
            "conversation.newMessage",
            {"objectId": "77", "threadId": "thread-77", "channel": "whatsapp", "direction": "INCOMING"},
        )

        with patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.delay") as mock_delay:
            handle_hubspot_event(event)

        mock_delay.assert_called_once_with("thread-77")

    def test_unknown_event_logs_only(self) -> None:
        event = _event("something.weird", {"objectId": "1"})
        handle_hubspot_event(event)

    def test_ticket_creation_noop(self) -> None:
        event = _event("ticket.creation", {"objectId": "1"})
        handle_hubspot_event(event)


class TestHandleTicketEnteredClosed:
    def test_owner_id_with_user_prefix_preserved_when_numeric(self) -> None:
        # ``userId:123`` is accepted (numeric after the colon) — the handler
        # preserves the full string and lets downstream code parse it again.
        with patch("apps.support.tasks.task_handle_ticket_closed.delay") as mock_delay:
            _handle_ticket_entered_closed(
                "ticket-1",
                "1699999999000",
                {"hubspot_owner_id": "userId:72733895"},
            )
        mock_delay.assert_called_once()
        _, args, _kwargs = mock_delay.mock_calls[0]
        assert args[-1] == "userId:72733895"

    def test_non_numeric_owner_becomes_none(self) -> None:
        with patch("apps.support.tasks.task_handle_ticket_closed.delay") as mock_delay:
            _handle_ticket_entered_closed(
                "ticket-1",
                "1699999999000",
                {"hubspot_owner_id": "StageCalculatedPropertiesRollup"},
            )
        mock_delay.assert_called_once()
        _, args, _kwargs = mock_delay.mock_calls[0]
        # Last positional argument is ``owner_str`` — should be None for
        # non-numeric HubSpot property rollups.
        assert args[-1] is None

    def test_missing_owner_becomes_none(self) -> None:
        with patch("apps.support.tasks.task_handle_ticket_closed.delay") as mock_delay:
            _handle_ticket_entered_closed("ticket-1", "1699999999000", {})
        mock_delay.assert_called_once()
        _, args, _kwargs = mock_delay.mock_calls[0]
        assert args[-1] is None
