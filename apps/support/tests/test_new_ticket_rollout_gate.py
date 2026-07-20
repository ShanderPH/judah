"""Regression tests for excluding the pre-deploy assignment backlog."""

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.integrations.hubspot.client import SUPPORT_PIPELINE_ID
from apps.support.auto_assign_service import sync_novo_stage_tickets
from apps.support.durable_assignment_service import reserve_next_assignment
from apps.support.matchmaker_service import _active_queue, enqueue_new_ticket
from apps.support.models import NewConversation


@pytest.mark.django_db
def test_existing_backlog_is_not_reservable() -> None:
    """Rows migrated with the safe default must never enter assignment."""
    backlog = NewConversation.objects.create(
        hubspot_ticket_id="PRE-DEPLOY-BACKLOG",
        entered_queue_at=timezone.now(),
    )

    reservation = reserve_next_assignment(backlog.hubspot_ticket_id)

    assert reservation.attempt is None
    assert reservation.reason == "queue_empty_or_claimed"
    assert _active_queue().count() == 0


@pytest.mark.django_db
@patch("apps.support.matchmaker_service.get_hubspot_client")
def test_live_webhook_ingestion_marks_new_ticket_eligible(mock_client_fn) -> None:
    """The canonical live ingestion path is the only opt-in boundary."""
    mock_client_fn.return_value.get_ticket_details.return_value = {
        "id": "POST-DEPLOY-NEW",
        "pipeline": SUPPORT_PIPELINE_ID,
        "owner_id": "",
    }

    conversation = enqueue_new_ticket("POST-DEPLOY-NEW")

    assert conversation is not None
    assert conversation.automatic_assignment_eligible is True
    assert _active_queue().get() == conversation


@pytest.mark.django_db
@patch("apps.support.auto_assign_service.get_hubspot_client")
def test_novo_backfill_does_not_opt_old_ticket_into_assignment(mock_client_fn) -> None:
    """Reconciliation may restore visibility but cannot authorize assignment."""
    mock_client_fn.return_value.search_tickets_in_novo_stage.return_value = [
        {
            "id": "BACKFILLED-NOVO",
            "pipeline": SUPPORT_PIPELINE_ID,
            "owner_id": "",
            "entered_novo_at": "1700000000000",
        }
    ]

    result = sync_novo_stage_tickets()

    conversation = NewConversation.objects.get(hubspot_ticket_id="BACKFILLED-NOVO")
    assert result["created"] == 1
    assert conversation.automatic_assignment_eligible is False
    assert _active_queue().count() == 0
