"""End-to-end state and audit tests for structured Supervisor decisions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from apps.ai_agents.agents.supervisor import SalomaoResponse
from apps.ai_agents.contracts import ConversationContext, SupervisorDecision, TriageDecision
from apps.ai_agents.models import AgentRun, ConversationInstance, ToolCallAuditLog
from apps.ai_agents.services.execution import (
    HUMAN_HANDOFF_CONFIRMATION,
    HUMAN_HANDOFF_OFF_HOURS_CONFIRMATION,
    apply_supervisor_result,
    handle_resolution_confirmation,
)
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
async def test_each_customer_message_has_one_independent_reply() -> None:
    instance = await sync_to_async(_instance)()

    def response(text: str) -> SalomaoResponse:
        return SalomaoResponse(
            session_id="hubspot-ticket-ticket-1",
            message=text,
            sources=[],
            requires_human_handoff=False,
            handoff_reason=None,
            agent_trace=[],
            tokens_used=1,
            model_name="test-model",
            latency_ms=1,
            decision=SupervisorDecision(
                outcome="candidate_resolved",
                final_response=text,
                confidence=0.9,
            ),
        )

    sender = AsyncMock(
        side_effect=[
            {"sent": True, "message_id": "out-1"},
            {"sent": True, "message_id": "out-2"},
        ]
    )
    with patch(
        "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
        new=sender,
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Primeira",
            result=response("Resposta da primeira"),
        )

        instance.state = ConversationInstance.State.AI_SERVICE_RUNNING
        instance.last_message_id = "message-2"
        await sync_to_async(instance.save)(update_fields=["state", "last_message_id", "updated_at"])
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Segunda",
            result=response("Resposta da segunda"),
        )

        # A retry of the second turn must reuse its successful audit rather
        # than publish the same answer twice.
        instance.state = ConversationInstance.State.AI_SERVICE_RUNNING
        await sync_to_async(instance.save)(update_fields=["state", "updated_at"])
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Segunda",
            result=response("Resposta da segunda"),
        )

    assert sender.await_count == 2
    keys = await sync_to_async(list)(
        ToolCallAuditLog.objects.filter(instance=instance, tool_name="send_thread_reply")
        .order_by("created_at")
        .values_list("idempotency_key", flat=True)
    )
    assert keys == [
        f"reply:{instance.pk}:message-1",
        f"reply:{instance.pk}:message-2",
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_handoff_routes_to_novo_and_waits_for_authoritative_webhook() -> None:
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

    effects: list[str] = []

    async def route_handoff(*_args, **_kwargs):
        effects.append("route")
        return {"updated": True}

    async def send_confirmation(_context, text):
        effects.append("reply")
        assert text == HUMAN_HANDOFF_CONFIRMATION
        return {"sent": True, "message_id": "out-2"}

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(side_effect=send_confirmation),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=AsyncMock(side_effect=route_handoff),
        ),
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
    assert instance.metadata["human_handoff_dispatch"]["route_updated"] is True
    assert instance.metadata["human_handoff_dispatch"]["queue_admission"] == "hubspot_stage_webhook"
    assert not await NewConversation.objects.filter(hubspot_ticket_id="ticket-1").aexists()
    assert await sync_to_async(
        ToolCallAuditLog.objects.filter(
            instance=instance,
            tool_name="assign_ticket_to_human_queue",
        ).exists
    )()
    assert effects == ["reply", "route"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_off_hours_handoff_warns_customer_and_still_routes_to_novo() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Vou transferir seu atendimento.",
        sources=[],
        requires_human_handoff=True,
        handoff_reason="Customer explicitly requested human assistance.",
        agent_trace=["handoff_policy: explicit_human_request"],
        tokens_used=0,
        model_name="handoff_policy",
        latency_ms=1,
        decision=SupervisorDecision(
            outcome="escalate_human",
            final_response="Vou transferir seu atendimento.",
            confidence=1.0,
        ),
    )
    send_reply = AsyncMock(return_value={"sent": True, "message_id": "out-off-hours"})
    route_handoff = AsyncMock(return_value={"updated": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=send_reply,
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=route_handoff,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context().model_copy(update={"is_off_hours": True}),
            message="Quero falar com uma pessoa",
            result=result,
        )

    assert send_reply.await_args.args[1] == HUMAN_HANDOFF_OFF_HOURS_CONFIRMATION
    route_handoff.assert_awaited_once()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.QUEUE_PENDING
    assert instance.metadata["human_handoff_dispatch"]["route_updated"] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_off_hours_regular_support_still_replies_normally() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Claro, vou te ajudar com isso.",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["salomao_chat: OK"],
        tokens_used=5,
        model_name="test-model",
        latency_ms=2,
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response="Claro, vou te ajudar com isso.",
            confidence=0.9,
        ),
    )
    send_reply = AsyncMock(return_value={"sent": True, "message_id": "out-normal"})

    with patch(
        "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
        new=send_reply,
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context().model_copy(update={"is_off_hours": True}),
            message="Como cadastro um membro?",
            result=result,
        )

    assert send_reply.await_args.args[1] == "Claro, vou te ajudar com isso."
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_handoff_notifies_before_hubspot_route_and_leaves_retryable_failure() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Vou transferir seu atendimento.",
        sources=[],
        requires_human_handoff=True,
        handoff_reason="Low confidence",
        agent_trace=["supervisor: mandatory_human_handoff"],
        tokens_used=5,
        model_name="test-model",
        latency_ms=3,
        decision=SupervisorDecision(
            outcome="escalate_human",
            final_response="Vou transferir seu atendimento.",
            confidence=0.3,
        ),
    )
    send_reply = AsyncMock(return_value={"sent": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=AsyncMock(return_value={"updated": False, "reason": "provider rejected"}),
        ) as route_handoff,
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=send_reply,
        ),
        pytest.raises(RuntimeError, match="provider rejected"),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Não entendi",
            result=result,
        )

    send_reply.assert_awaited_once()
    assert send_reply.await_args.args[1] == HUMAN_HANDOFF_CONFIRMATION
    route_handoff.assert_awaited_once()
    assert not await NewConversation.objects.filter(hubspot_ticket_id="ticket-1").aexists()

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.HUMAN_HANDOFF_REQUESTED
    successful_retry = AsyncMock(return_value={"updated": True})
    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=send_reply,
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=successful_retry,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Não entendi",
            result=result,
        )

    send_reply.assert_awaited_once()
    successful_retry.assert_awaited_once()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.QUEUE_PENDING
    assert not await NewConversation.objects.filter(hubspot_ticket_id="ticket-1").aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_handoff_does_not_route_before_customer_notification_succeeds() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Vou transferir seu atendimento.",
        sources=[],
        requires_human_handoff=True,
        handoff_reason="Customer explicitly requested human assistance.",
        agent_trace=["handoff_policy: explicit_human_request"],
        tokens_used=0,
        model_name="handoff_policy",
        latency_ms=1,
        decision=SupervisorDecision(
            outcome="escalate_human",
            final_response="Vou transferir seu atendimento.",
            confidence=1.0,
        ),
    )
    route_handoff = AsyncMock(return_value={"updated": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": False, "reason": "reply rejected"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=route_handoff,
        ),
        pytest.raises(RuntimeError, match="reply rejected"),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Quero falar com um humano",
            result=result,
        )

    route_handoff.assert_not_awaited()
    assert not await NewConversation.objects.filter(hubspot_ticket_id="ticket-1").aexists()


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
