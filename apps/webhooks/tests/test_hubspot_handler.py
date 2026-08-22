from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.webhooks.handlers.hubspot_handler import handle_hubspot_event


def _event(event_type: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(event_type=event_type, payload=payload, event_id="provider-1", pk="row-1")


@pytest.mark.django_db
def test_support_new_stage_dispatches_matchmaker(django_capture_on_commit_callbacks, settings) -> None:
    event = _event(
        "ticket.propertyChange",
        {
            "objectId": "ticket-1",
            "propertyName": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_NEW_STAGE_ID}",
            "propertyValue": "123",
        },
    )

    with (
        patch("apps.support.availability_runtime.may_ingest_queue", return_value=True),
        patch("apps.support.tasks.task_matchmaker_assign_single.delay") as assign,
        django_capture_on_commit_callbacks(execute=True),
    ):
        handle_hubspot_event(event)

    assign.assert_called_once_with("ticket-1", "123", "provider-1")


def test_support_closed_stage_dispatches_closure(settings) -> None:
    event = _event(
        "ticket.propertyChange",
        {
            "objectId": "ticket-2",
            "propertyName": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}",
            "propertyValue": "456",
            "hubspot_owner_id": "userId:99",
        },
    )

    with patch("apps.support.tasks.task_handle_ticket_closed.delay") as close:
        handle_hubspot_event(event)

    close.assert_called_once_with("ticket-2", "456", "userId:99")


def test_owner_change_dispatches_preserved_owner_task() -> None:
    payload = {"objectId": "ticket-3", "propertyName": "hubspot_owner_id", "propertyValue": "42"}

    with patch("apps.support.tasks.task_handle_owner_change.delay") as owner_change:
        handle_hubspot_event(_event("ticket.propertyChange", payload))

    owner_change.assert_called_once_with("ticket-3", "42", payload)


def test_conversation_message_has_no_local_bot_dispatch() -> None:
    handle_hubspot_event(_event("conversation.newMessage", {"objectId": "thread-1", "messageId": "message-1"}))


def test_removed_ai_stage_property_has_no_side_effect() -> None:
    event = _event(
        "ticket.propertyChange",
        {
            "objectId": "ticket-4",
            "propertyName": "hs_v2_date_entered_939271304",
            "propertyValue": "123",
        },
    )

    with (
        patch("apps.support.tasks.task_matchmaker_assign_single.delay") as assign,
        patch("apps.support.tasks.task_handle_ticket_closed.delay") as close,
        patch("apps.support.tasks.task_handle_owner_change.delay") as owner_change,
    ):
        handle_hubspot_event(event)

    assign.assert_not_called()
    close.assert_not_called()
    owner_change.assert_not_called()
