"""Release blocker reproducer, explicitly invoked outside the normal test suite."""

from unittest.mock import patch

from apps.support.lifecycle_occurrence_service import open_from_proven_occurrence
from apps.support.models import SupportConversationCycle, SupportLifecycleOccurrence
from apps.support.tasks import task_reconcile_lifecycle_occurrence
from apps.support.tests.test_lifecycle_entry_recovery import record_entry


def test_terminal_entry_is_not_projected_by_an_earlier_execution(settings) -> None:
    """Simulate two executions reaching projection and budget exhaustion in order."""
    settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_ATTEMPTS = 1
    occurrence = record_entry("synthetic-overlap")
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)

    def exhaust_before_projection(**kwargs):
        # Deterministically simulate the next due task arriving while the first pauses.
        SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)
        assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "repair_required"
        return open_from_proven_occurrence(**kwargs)

    with patch(
        "apps.support.lifecycle_occurrence_service.open_from_proven_occurrence", side_effect=exhaust_before_projection
    ):
        task_reconcile_lifecycle_occurrence.run(str(occurrence.pk))

    occurrence.refresh_from_db()
    assert occurrence.processing_status == "repair_required"
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id="synthetic-overlap").exists()
