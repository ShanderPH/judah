"""Tests for lifecycle guardrails, handoff packages, and watchdog recovery."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai_agents.contracts import ConversationContext, ConversationMessage, TriageDecision
from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.handoff import build_handoff_package
from apps.ai_agents.services.tool_permissions import is_tool_allowed
from apps.ai_agents.services.watchdog import run_lifecycle_watchdog


def test_tool_permissions_are_state_scoped() -> None:
    assert is_tool_allowed(ConversationInstance.State.AI_SERVICE_RUNNING, "send_thread_reply") is True
    assert is_tool_allowed(ConversationInstance.State.HUMAN_HANDOFF_REQUESTED, "assign_ticket_to_human_queue") is True
    assert is_tool_allowed(ConversationInstance.State.CLOSED, "send_thread_reply") is False
    assert is_tool_allowed(ConversationInstance.State.TRIAGE_RUNNING, "create_contact") is False


@pytest.mark.django_db
def test_build_handoff_package_includes_operational_context() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:thread-1",
        hubspot_thread_id="thread-1",
        hubspot_ticket_id="ticket-1",
        hubspot_contact_id="contact-1",
        channel="chat",
        state=ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
    )
    context = ConversationContext(
        channel="hubspot",
        session_id="hubspot-thread-thread-1",
        recent_messages=[
            ConversationMessage(direction="INCOMING", text="Preciso falar com humano", message_id="m1"),
        ],
    )
    triage = TriageDecision(
        rota="ESCALAR_IMEDIATAMENTE",
        prioridade="ALTA",
        sentimento="negativo",
        tags=["humano"],
    )

    package = build_handoff_package(
        instance=instance,
        reason="User requested a human.",
        conversation_context=context,
        triage_decision=triage,
        ai_summary="Cliente pediu atendimento humano.",
    )

    assert package["hubspot_thread_id"] == "thread-1"
    assert package["reason"] == "User requested a human."
    assert package["priority"] == "ALTA"
    assert package["tags"] == ["humano"]
    assert package["recent_messages"][0]["text"] == "Preciso falar com humano"


@pytest.mark.django_db
def test_watchdog_marks_stuck_instances_retryable() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:stuck-1",
        hubspot_thread_id="stuck-1",
        state=ConversationInstance.State.TRIAGE_RUNNING,
        last_activity_at=timezone.now() - timedelta(minutes=30),
    )

    result = run_lifecycle_watchdog(limit=10, max_failures=3)

    instance.refresh_from_db()
    assert result.scanned == 1
    assert result.marked_retryable == 1
    assert instance.state == ConversationInstance.State.FAILED_RETRYABLE
    assert instance.failure_count == 1


@pytest.mark.django_db
def test_watchdog_marks_repeated_failures_terminal() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:stuck-2",
        hubspot_thread_id="stuck-2",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
        failure_count=2,
        last_activity_at=timezone.now() - timedelta(minutes=30),
    )

    result = run_lifecycle_watchdog(limit=10, max_failures=3)

    instance.refresh_from_db()
    assert result.scanned == 1
    assert result.marked_terminal == 1
    assert instance.state == ConversationInstance.State.FAILED_TERMINAL
    assert instance.failure_count == 3
