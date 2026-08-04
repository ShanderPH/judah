"""Regression tests for independently measurable reopened attendances."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance, ConversationServiceCycle
from apps.ai_agents.services.lifecycle import LifecycleEngine
from apps.ai_agents.services.service_cycles import ensure_current_service_cycle, service_cycle_context


@pytest.mark.django_db
def test_terminal_reopen_rotates_cycle_and_reopens_same_instance() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:reopen-cycle",
        hubspot_thread_id="reopen-cycle",
        state=ConversationInstance.State.CLOSED,
        closed_at=timezone.now(),
        assigned_agent_id="previous-owner",
    )
    previous_cycle = ensure_current_service_cycle(instance)

    LifecycleEngine().transition(
        instance,
        ConversationInstance.State.CONTEXT_HYDRATING,
        reason="Verified incoming customer message reopened the conversation.",
        source_event_id="reopen-event-1",
        allow_terminal_reopen=True,
    )

    instance.refresh_from_db()
    cycles = list(instance.service_cycles.order_by("sequence"))
    assert instance.state == ConversationInstance.State.CONTEXT_HYDRATING
    assert instance.closed_at is None
    assert instance.assigned_agent_id is None
    assert len(cycles) == 2
    assert cycles[0].pk == previous_cycle.pk
    assert cycles[0].status == ConversationServiceCycle.Status.CLOSED
    assert cycles[1].status == ConversationServiceCycle.Status.OPEN
    assert cycles[1].sequence == 2
    assert cycles[1].idempotency_key != cycles[0].idempotency_key
    assert cycles[1].opened_from_state == ConversationInstance.State.CLOSED
    assert cycles[1].opened_by_event_id == "reopen-event-1"


@pytest.mark.django_db
def test_reopen_retry_does_not_create_an_extra_cycle() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:reopen-cycle-retry",
        hubspot_thread_id="reopen-cycle-retry",
        state=ConversationInstance.State.CLOSED,
        closed_at=timezone.now(),
    )
    engine = LifecycleEngine()

    engine.transition(
        instance,
        ConversationInstance.State.CONTEXT_HYDRATING,
        reason="Verified reopen.",
        source_event_id="same-reopen-event",
        allow_terminal_reopen=True,
    )
    engine.transition(
        instance,
        ConversationInstance.State.CONTEXT_HYDRATING,
        reason="Duplicate delivery.",
        source_event_id="same-reopen-event",
        allow_terminal_reopen=True,
    )

    assert instance.service_cycles.count() == 2
    assert instance.service_cycles.get(status=ConversationServiceCycle.Status.OPEN).sequence == 2


@pytest.mark.django_db
def test_service_cycle_context_marks_reopened_attendance() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:reopen-context",
        hubspot_thread_id="reopen-context",
        state=ConversationInstance.State.CLOSED,
        closed_at=timezone.now(),
    )
    LifecycleEngine().transition(
        instance,
        ConversationInstance.State.CONTEXT_HYDRATING,
        reason="New customer request after closure.",
        allow_terminal_reopen=True,
    )

    context = service_cycle_context(instance)

    assert context.sequence == 2
    assert context.is_reopened is True
    assert context.reopen_count == 1
    assert context.opened_from_state == ConversationInstance.State.CLOSED
    assert context.idempotency_key


@pytest.mark.django_db
def test_cycle_correlates_transition_agent_run_and_tool_audit() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:cycle-ledgers",
        hubspot_thread_id="cycle-ledgers",
        state=ConversationInstance.State.CONTEXT_HYDRATING,
    )
    engine = LifecycleEngine()
    engine.transition(
        instance,
        ConversationInstance.State.CONTEXT_READY,
        reason="Context ready.",
    )
    run = engine.record_agent_run(
        instance=instance,
        agent_name="SalomaoSupervisor",
        input_snapshot={"message": "fingerprint"},
    )
    audit = engine.record_tool_call(
        instance=instance,
        agent_run=run,
        tool_name="send_thread_reply",
        idempotency_key="cycle-ledgers:reply",
        input_payload={"reply": "fingerprint"},
    )

    transition = instance.state_transitions.get(to_state=ConversationInstance.State.CONTEXT_READY)
    cycle = instance.service_cycles.get()
    assert transition.service_cycle_id == cycle.pk
    assert run.service_cycle_id == cycle.pk
    assert audit.service_cycle_id == cycle.pk
