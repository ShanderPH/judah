"""End-to-end state and audit tests for structured Supervisor decisions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from apps.ai_agents.agents.supervisor import SalomaoResponse
from apps.ai_agents.contracts import ConversationContext, SupervisorDecision, TriageDecision
from apps.ai_agents.models import AgentRun, ConversationInstance, ToolCallAuditLog
from apps.ai_agents.services.execution import apply_supervisor_result, handle_resolution_confirmation
from apps.support.models import NewConversation


def _context() -> ConversationContext:
    return ConversationContext(
        channel="hubspot",
        session_id="hubspot-ticket-ticket-1",
        ticket_id="ticket-1",
        thread_id="thread-1",
        can_send_reply=True,
    )


def _instance() -> ConversationInstance:
    return ConversationInstance.objects.create(
        idempotency_key="conversation:thread:thread-1",
        hubspot_thread_id="thread-1",
        hubspot_ticket_id="ticket-1",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
        last_message_id="message-1",
        ai_session_id="hubspot-ticket-ticket-1",
    )


def _triage() -> TriageDecision:
    return TriageDecision(
        rota="SUPORTE_TECNICO_N1",
        prioridade="MEDIA",
        sentimento="neutro",
        confidence=0.9,
        evidences=["erro ao acessar"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_candidate_resolution_waits_without_hidden_confirmation_prompt() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Ajuste concluído.",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["heimdall: OK", "salomao_chat: OK"],
        tokens_used=15,
        model_name="test-model",
        latency_ms=5,
        triage_decision=_triage(),
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response="Ajuste concluído.",
            confidence=0.9,
        ),
    )

    with patch(
        "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
        new=AsyncMock(return_value={"sent": True, "message_id": "out-1"}),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Meu acesso falhou",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert instance.metadata["awaiting_resolution_confirmation"] is False
    assert await sync_to_async(AgentRun.objects.filter(instance=instance, agent_name="Heimdall").exists)()
    assert await sync_to_async(AgentRun.objects.filter(instance=instance, agent_name="SalomaoSupervisor").exists)()
    audit = await sync_to_async(ToolCallAuditLog.objects.get)(
        instance=instance,
        tool_name="send_thread_reply",
    )
    assert audit.status == ToolCallAuditLog.Status.SUCCEEDED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_handoff_builds_package_and_enters_matchmaker_queue() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Vou transferir seu atendimento.",
        sources=[],
        requires_human_handoff=True,
        handoff_reason="Low confidence",
        agent_trace=["heimdall: OK", "supervisor: mandatory_human_handoff"],
        tokens_used=5,
        model_name="test-model",
        latency_ms=3,
        triage_decision=_triage().model_copy(update={"confidence": 0.3}),
        decision=SupervisorDecision(
            outcome="escalate_human",
            final_response="Vou transferir seu atendimento.",
            risk_flags=["low_confidence"],
            confidence=0.3,
        ),
    )

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-2"}),
        ),
        patch("apps.support.tasks.task_matchmaker_drain_queue.delay") as drain,
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Não entendi",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.QUEUE_PENDING
    assert "handoff_package" in instance.metadata
    assert await sync_to_async(NewConversation.objects.filter(hubspot_ticket_id="ticket-1").exists)()
    assert await sync_to_async(
        ToolCallAuditLog.objects.filter(
            instance=instance,
            tool_name="assign_ticket_to_human_queue",
        ).exists
    )()
    drain.assert_called_once()


@pytest.mark.django_db
def test_customer_confirmation_closes_candidate_resolution() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:confirmation",
        hubspot_thread_id="confirmation",
        state=ConversationInstance.State.CONTEXT_HYDRATING,
        metadata={"awaiting_resolution_confirmation": True},
    )

    assert handle_resolution_confirmation(instance, "Sim, resolveu") is True

    instance.refresh_from_db()
    assert instance.state == ConversationInstance.State.CLOSED
    assert instance.metadata["awaiting_resolution_confirmation"] is False
