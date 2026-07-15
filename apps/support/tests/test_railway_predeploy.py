"""Tests for migration-aware Railway pre-deploy behavior."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.support.models import NewConversation


def _queue_ticket(ticket_id: str, status: str) -> NewConversation:
    return NewConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        pipeline_id="pipeline",
        queue_status=status,
        entered_queue_at=timezone.now(),
    )


@pytest.mark.django_db
def test_pending_migration_suppresses_active_assignment_backlog() -> None:
    pending = _queue_ticket("pending", NewConversation.QueueStatus.PENDING)
    queued = _queue_ticket("queued", NewConversation.QueueStatus.QUEUED)
    quarantined = _queue_ticket("failed", NewConversation.QueueStatus.FAILED)
    quarantined.failure_code = "hubspot_ticket_not_found"
    quarantined.save(update_fields=["failure_code", "updated_at"])

    executor = MagicMock()
    executor.loader.graph.leaf_nodes.return_value = [("support", "0014")]
    executor.migration_plan.return_value = [object()]
    with (
        patch(
            "apps.support.management.commands.railway_predeploy.MigrationExecutor",
            return_value=executor,
        ),
        patch("apps.support.management.commands.railway_predeploy.call_command") as migrate,
    ):
        call_command("railway_predeploy", verbosity=0)

    migrate.assert_called_once_with("migrate", interactive=False, verbosity=0)
    pending.refresh_from_db()
    queued.refresh_from_db()
    quarantined.refresh_from_db()
    assert pending.queue_status == NewConversation.QueueStatus.FAILED
    assert queued.queue_status == NewConversation.QueueStatus.FAILED
    assert pending.failure_code == "predeploy_queue_cleared"
    assert queued.failure_code == "predeploy_queue_cleared"
    assert quarantined.failure_code == "hubspot_ticket_not_found"


@pytest.mark.django_db
def test_deploy_without_pending_migration_preserves_queue() -> None:
    pending = _queue_ticket("pending", NewConversation.QueueStatus.PENDING)
    executor = MagicMock()
    executor.loader.graph.leaf_nodes.return_value = [("support", "0014")]
    executor.migration_plan.return_value = []
    with (
        patch(
            "apps.support.management.commands.railway_predeploy.MigrationExecutor",
            return_value=executor,
        ),
        patch("apps.support.management.commands.railway_predeploy.call_command"),
    ):
        call_command("railway_predeploy", verbosity=0)

    pending.refresh_from_db()
    assert pending.queue_status == NewConversation.QueueStatus.PENDING
