from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.watchdog import run_lifecycle_watchdog


@pytest.mark.django_db
def test_watchdog_marks_stuck_generic_instance_retryable() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="watchdog:generic",
        state=ConversationInstance.State.CONTEXT_HYDRATING,
        last_activity_at=timezone.now() - timedelta(minutes=20),
    )

    result = run_lifecycle_watchdog()

    instance.refresh_from_db()
    assert result.marked_retryable == 1
    assert instance.state == ConversationInstance.State.FAILED_RETRYABLE


@pytest.mark.django_db
def test_watchdog_terminalizes_after_bounded_failures() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="watchdog:terminal",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
        failure_count=2,
        last_activity_at=timezone.now() - timedelta(minutes=20),
    )

    result = run_lifecycle_watchdog(max_failures=3)

    instance.refresh_from_db()
    assert result.marked_terminal == 1
    assert instance.state == ConversationInstance.State.FAILED_TERMINAL
