"""End-to-end state and audit tests for structured Supervisor decisions."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from apps.ai_agents.agents.supervisor import SalomaoResponse
from apps.ai_agents.contracts import ConversationContext, SupervisorDecision, TriageDecision
from apps.ai_agents.models import AgentRun, ConversationInstance, ToolCallAuditLog
from apps.ai_agents.services.execution import (
    HUMAN_HANDOFF_CONFIRMATION,
    HUMAN_HANDOFF_OFF_HOURS_CONFIRMATION,
    apply_supervisor_result,
    handle_resolution_confirmation,
    publish_handoff_observation,
    resume_pending_ticket_effect,
)
from apps.support.models import NewConversation


@pytest.fixture(autouse=True)
def _mock_hubspot_internal_observation() -> Iterator[AsyncMock]:
    observation = AsyncMock(
        return_value={
            "created": True,
            "thread_id": "thread-1",
            "message_id": "comment-1",
        }
    )
    with patch(
        "apps.ai_agents.services.hubspot.create_hubspot_thread_comment",
        new=observation,
    ):
        yield observation


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
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-triage",
    HUBSPOT_CLOSED_STAGE_ID="ai-closed",
)
async def test_candidate_resolution_closes_ticket_after_reply() -> None:
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

    close_route = AsyncMock(return_value={"updated": True})
    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-1"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=close_route,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Meu acesso falhou",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.CLOSED
    assert instance.metadata["awaiting_resolution_confirmation"] is False
    assert instance.metadata["ai_resolution_dispatch"] == {
        "closed": True,
        "ticket_id": "ticket-1",
        "pipeline_id": "ai-triage",
        "stage_id": "ai-closed",
        "owner_mutated": False,
    }
    close_route.assert_awaited_once_with(
        "ticket-1",
        "ai-closed",
        pipeline_id="ai-triage",
        eligibility_thread_id="thread-1",
        expected_customer_turn_id="message-1",
    )
    assert await sync_to_async(AgentRun.objects.filter(instance=instance, agent_name="Heimdall").exists)()
    assert await sync_to_async(AgentRun.objects.filter(instance=instance, agent_name="SalomaoSupervisor").exists)()
    audit = await sync_to_async(ToolCallAuditLog.objects.get)(
        instance=instance,
        tool_name="send_thread_reply",
    )
    assert audit.status == ToolCallAuditLog.Status.SUCCEEDED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stale_reply_is_safely_suppressed_without_closing_or_retrying() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Resposta que ficou obsoleta.",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["salomao_chat: OK"],
        tokens_used=5,
        model_name="test-model",
        latency_ms=2,
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response="Resposta que ficou obsoleta.",
            confidence=0.9,
        ),
    )
    close_route = AsyncMock(return_value={"updated": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(
                return_value={
                    "sent": False,
                    "suppressed": True,
                    "retryable": False,
                    "reason": "ticket_owned_by_human",
                }
            ),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=close_route,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Aguardando",
            result=result,
        )

    close_route.assert_not_awaited()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.IGNORED
    assert instance.failure_count == 0
    assert instance.metadata["ai_reply_suppressed"]["reason"] == "ticket_owned_by_human"
    audit = await sync_to_async(ToolCallAuditLog.objects.get)(
        instance=instance,
        tool_name="send_thread_reply",
    )
    assert audit.status == ToolCallAuditLog.Status.SUCCEEDED
    assert audit.output["suppressed"] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-triage",
    HUBSPOT_CLOSED_STAGE_ID="ai-closed",
)
async def test_candidate_resolution_never_writes_owner() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Ajuste concluído.",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["salomao_chat: OK"],
        tokens_used=5,
        model_name="test-model",
        latency_ms=2,
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response="Ajuste concluído.",
            confidence=0.9,
        ),
    )
    conversation_context = _context().model_copy(update={"owner_id": "human-owner"})

    close_route = AsyncMock(return_value={"updated": True})
    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-human-owner"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=close_route,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=conversation_context,
            message="Meu acesso foi normalizado",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.CLOSED
    assert instance.metadata["ai_resolution_dispatch"]["owner_mutated"] is False
    close_route.assert_awaited_once_with(
        "ticket-1",
        "ai-closed",
        pipeline_id="ai-triage",
        eligibility_thread_id="thread-1",
        expected_customer_turn_id="message-1",
    )


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
                outcome="waiting_customer",
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
async def test_handoff_routes_to_novo_and_waits_for_authoritative_webhook(
    _mock_hubspot_internal_observation: AsyncMock,
) -> None:
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

    route_update = AsyncMock(side_effect=route_handoff)

    async def send_confirmation(_context, text):
        effects.append("reply")
        assert text == HUMAN_HANDOFF_CONFIRMATION
        return {"sent": True, "message_id": "out-2"}

    async def create_observation(*_args, **_kwargs):
        effects.append("observation")
        return {
            "created": True,
            "thread_id": "thread-1",
            "message_id": "comment-1",
        }

    _mock_hubspot_internal_observation.side_effect = create_observation

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(side_effect=send_confirmation),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=route_update,
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
    assert instance.metadata["human_handoff_dispatch"]["observation"]["created"] is True
    assert instance.metadata["handoff_package"]["customer_tone"] == "Indeterminado"
    assert instance.metadata["handoff_package"]["conversation_summary"]
    assert instance.metadata["handoff_package"]["recommended_next_step"]
    assert not await NewConversation.objects.filter(hubspot_ticket_id="ticket-1").aexists()
    assert await sync_to_async(
        ToolCallAuditLog.objects.filter(
            instance=instance,
            tool_name="assign_ticket_to_human_queue",
        ).exists
    )()
    route_call = route_update.await_args
    assert route_call.args == ("ticket-1", "939275049")
    assert route_call.kwargs == {
        "pipeline_id": "636459134",
        "eligibility_thread_id": "thread-1",
        "expected_customer_turn_id": "message-1",
    }
    assert effects == ["reply", "route", "observation"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_handoff_route_is_idempotent_per_customer_turn() -> None:
    instance = await sync_to_async(_instance)()

    def handoff_result() -> SalomaoResponse:
        return SalomaoResponse(
            session_id="hubspot-ticket-ticket-1",
            message="Vou transferir seu atendimento.",
            sources=[],
            requires_human_handoff=True,
            handoff_reason="Customer requested a human.",
            agent_trace=["supervisor: mandatory_human_handoff"],
            tokens_used=2,
            model_name="test-model",
            latency_ms=1,
            triage_decision=_triage(),
            decision=SupervisorDecision(
                outcome="escalate_human",
                final_response="Vou transferir seu atendimento.",
                confidence=1.0,
            ),
        )

    send_confirmation = AsyncMock(
        side_effect=[
            {"sent": True, "message_id": "handoff-confirmation-1"},
            {"sent": True, "message_id": "handoff-confirmation-2"},
        ]
    )
    route_update = AsyncMock(return_value={"updated": True})
    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=send_confirmation,
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=route_update,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Quero falar com uma pessoa",
            result=handoff_result(),
        )

        instance.state = ConversationInstance.State.AI_SERVICE_RUNNING
        instance.last_message_id = "message-2"
        await sync_to_async(instance.save)(update_fields=["state", "last_message_id", "updated_at"])
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Ainda quero falar com uma pessoa",
            result=handoff_result(),
        )

        instance.state = ConversationInstance.State.AI_SERVICE_RUNNING
        await sync_to_async(instance.save)(update_fields=["state", "updated_at"])
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Ainda quero falar com uma pessoa",
            result=handoff_result(),
        )

    assert send_confirmation.await_count == 2
    assert route_update.await_count == 2
    keys = await sync_to_async(list)(
        ToolCallAuditLog.objects.filter(
            instance=instance,
            tool_name="assign_ticket_to_human_queue",
        )
        .order_by("created_at")
        .values_list("idempotency_key", flat=True)
    )
    assert keys == [
        f"handoff:v4:{instance.pk}:ticket-1:message-1:636459134:939275049",
        f"handoff:v4:{instance.pk}:ticket-1:message-2:636459134:939275049",
    ]


@pytest.mark.django_db
def test_handoff_observation_is_idempotent(_mock_hubspot_internal_observation: AsyncMock) -> None:
    instance = _instance()
    instance.state = ConversationInstance.State.HUMAN_HANDOFF_REQUESTED
    instance.save(update_fields=["state", "updated_at"])
    package = {
        "hubspot_thread_id": "thread-1",
        "source_message_id": "message-1",
        "reason": "Customer explicitly requested human assistance.",
        "priority": "ALTA",
        "missing_data": [],
        "customer_tone": "Calmo/neutro",
        "customer_tone_context": "Sem sinais de irritação.",
        "conversation_summary": "O cliente solicitou atendimento humano.",
        "recommended_next_step": "Assumir a conversa e continuar pelo histórico.",
    }

    first = publish_handoff_observation(instance=instance, package=package)
    instance.last_message_id = "message-2"
    instance.save(update_fields=["last_message_id", "updated_at"])
    second = publish_handoff_observation(instance=instance, package=package)

    assert first["created"] is True
    assert second == first
    assert _mock_hubspot_internal_observation.await_count == 1
    audit = ToolCallAuditLog.objects.get(instance=instance, tool_name="add_internal_note")
    assert audit.status == ToolCallAuditLog.Status.SUCCEEDED
    assert "conversation_summary" not in audit.input
    assert audit.input["observation"]["sha256"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_observation_failure_never_cancels_novo_handoff() -> None:
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

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "reply-1"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=AsyncMock(return_value={"updated": True}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.create_hubspot_thread_comment",
            new=AsyncMock(return_value={"created": False, "reason": "http:503"}),
        ),
        patch("apps.ai_agents.tasks.publish_handoff_observation_task.delay") as retry_observation,
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Quero falar com uma pessoa",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.QUEUE_PENDING
    assert instance.metadata["human_handoff_dispatch"]["route_updated"] is True
    observation = instance.metadata["human_handoff_dispatch"]["observation"]
    assert observation["created"] is False
    assert observation["retry_scheduled"] is True
    retry_observation.assert_called_once_with(str(instance.pk))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@override_settings(
    HUBSPOT_OFF_HOURS_PIPELINE_ID="off-hours-pipeline",
    HUBSPOT_OFF_HOURS_STAGE_ID="off-hours-stage",
)
async def test_off_hours_handoff_warns_customer_and_uses_configured_route() -> None:
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
    route_handoff.assert_awaited_once_with(
        "ticket-1",
        "off-hours-stage",
        pipeline_id="off-hours-pipeline",
        eligibility_thread_id="thread-1",
        expected_customer_turn_id="message-1",
    )
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.QUEUE_PENDING
    assert instance.metadata["human_handoff_dispatch"]["route_updated"] is True
    assert instance.metadata["human_handoff_dispatch"]["queue_admission"] == "off_hours_stage_workflow"
    assert instance.metadata["human_handoff_dispatch"]["is_off_hours"] is True


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

    close_route = AsyncMock(return_value={"updated": True})
    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=send_reply,
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=close_route,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context().model_copy(update={"is_off_hours": True}),
            message="Como cadastro um membro?",
            result=result,
        )

    assert send_reply.await_args.args[1] == "Claro, vou te ajudar com isso."
    close_route.assert_awaited_once()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.CLOSED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_waiting_customer_reply_keeps_ticket_open() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Qual tipo de pagamento você deseja estornar?",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["salomao_chat: clarification"],
        tokens_used=5,
        model_name="test-model",
        latency_ms=2,
        decision=SupervisorDecision(
            outcome="waiting_customer",
            final_response="Qual tipo de pagamento você deseja estornar?",
            missing_data=["payment_type"],
            confidence=0.9,
        ),
    )
    close_route = AsyncMock(return_value={"updated": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-question"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=close_route,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Como faço estorno?",
            result=result,
        )

    close_route.assert_not_awaited()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert instance.metadata["waiting_for_fields"] == ["payment_type"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_candidate_resolution_with_open_question_is_kept_open() -> None:
    instance = await sync_to_async(_instance)()
    response = (
        "Confira as configurações do evento. "
        "Em qual etapa o erro acontece? Se puder, me envie um print da mensagem de erro."
    )
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message=response,
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["salomao_chat: OK"],
        tokens_used=5,
        model_name="test-model",
        latency_ms=2,
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response=response,
            confidence=0.9,
        ),
    )
    close_route = AsyncMock(return_value={"updated": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-question"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=close_route,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Meu evento não aparece",
            result=result,
        )

    close_route.assert_not_awaited()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    decision = instance.metadata["last_supervisor_decision"]
    assert decision["outcome"] == "waiting_customer"
    assert "candidate_resolution_requires_customer_input" in decision["risk_flags"]
    run = await AgentRun.objects.aget(instance=instance, agent_name="SalomaoSupervisor")
    assert run.output_structured["outcome"] == "waiting_customer"


@pytest.mark.django_db
def test_legacy_close_replay_cannot_close_an_open_question() -> None:
    instance = _instance()
    instance.state = ConversationInstance.State.FAILED_RETRYABLE
    instance.save(update_fields=["state", "updated_at"])
    response = "Em qual etapa o erro acontece? Se puder, me envie um print da mensagem exibida."
    decision = SupervisorDecision(
        outcome="candidate_resolved",
        final_response=response,
        confidence=0.9,
    )
    agent_run = AgentRun.objects.create(
        instance=instance,
        agent_name="SalomaoSupervisor",
        model_name="salomao_v1",
        output_structured=decision.model_dump(mode="json"),
        status=AgentRun.Status.SUCCEEDED,
    )
    audit = ToolCallAuditLog.objects.create(
        instance=instance,
        agent_run=agent_run,
        tool_name="update_ticket_stage",
        input={"ticket_id": "ticket-1"},
        status=ToolCallAuditLog.Status.FAILED,
        idempotency_key="legacy-close-open-question",
        error_message="provider timeout",
    )

    with patch("apps.ai_agents.services.hubspot.update_hubspot_ticket_route") as close_route:
        result = resume_pending_ticket_effect(instance)

    close_route.assert_not_called()
    instance.refresh_from_db()
    audit.refresh_from_db()
    assert result == {
        "closed": False,
        "suppressed": True,
        "reason": "candidate_resolution_requires_customer_input",
    }
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert instance.metadata["last_supervisor_decision"]["outcome"] == "waiting_customer"
    assert audit.status == ToolCallAuditLog.Status.SUCCEEDED
    assert audit.output == result


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ai_resolution_route_failure_is_retryable() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Orientação concluída.",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=[],
        tokens_used=1,
        model_name="test-model",
        latency_ms=1,
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response="Orientação concluída.",
            confidence=0.9,
        ),
    )

    send_reply = AsyncMock(return_value={"sent": True, "message_id": "out-resolution"})
    failed_route = AsyncMock(return_value={"updated": False, "reason": "http:503"})
    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=send_reply,
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=failed_route,
        ),
        pytest.raises(RuntimeError, match="http:503"),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Como faço?",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.FAILED_RETRYABLE
    audit = await sync_to_async(ToolCallAuditLog.objects.get)(
        instance=instance,
        tool_name="update_ticket_stage",
    )
    assert audit.status == ToolCallAuditLog.Status.FAILED

    successful_replay = AsyncMock(return_value={"updated": True})
    with patch(
        "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
        new=successful_replay,
    ):
        replayed = await sync_to_async(resume_pending_ticket_effect)(instance)

    assert replayed is not None
    send_reply.assert_awaited_once()
    successful_replay.assert_awaited_once()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.CLOSED
    await sync_to_async(audit.refresh_from_db)()
    assert audit.status == ToolCallAuditLog.Status.SUCCEEDED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_human_takeover_after_resolution_reply_suppresses_close_without_retry() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Orientação concluída.",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=[],
        tokens_used=1,
        model_name="test-model",
        latency_ms=1,
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response="Orientação concluída.",
            confidence=0.9,
        ),
    )

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-resolution"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=AsyncMock(
                return_value={
                    "updated": False,
                    "suppressed": True,
                    "retryable": False,
                    "reason": "ticket_owned_by_human",
                }
            ),
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Como faço?",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.IGNORED
    assert instance.failure_count == 0
    assert instance.next_retry_at is None
    assert instance.metadata["ai_resolution_dispatch"] == {
        "closed": False,
        "ticket_id": "ticket-1",
        "pipeline_id": "636594474",
        "stage_id": "939271307",
        "owner_mutated": False,
        "suppressed": True,
        "reason": "ticket_owned_by_human",
    }
    audit = await sync_to_async(ToolCallAuditLog.objects.get)(
        instance=instance,
        tool_name="update_ticket_stage",
    )
    assert audit.status == ToolCallAuditLog.Status.SUCCEEDED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("current_owner_id", ["ai-owner", "human-owner", ""])
async def test_handoff_never_writes_owner(current_owner_id: str) -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Vou transferir.",
        sources=[],
        requires_human_handoff=True,
        handoff_reason="Customer explicitly requested human assistance.",
        agent_trace=[],
        tokens_used=0,
        model_name="handoff_policy",
        latency_ms=1,
        decision=SupervisorDecision(
            outcome="escalate_human",
            final_response="Vou transferir.",
            confidence=1.0,
        ),
    )
    route_handoff = AsyncMock(return_value={"updated": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-handoff"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=route_handoff,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context().model_copy(update={"owner_id": current_owner_id}),
            message="Quero falar com um humano",
            result=result,
        )

    route_handoff.assert_awaited_once_with(
        "ticket-1",
        "939275049",
        pipeline_id="636459134",
        eligibility_thread_id="thread-1",
        expected_customer_turn_id="message-1",
    )
    await sync_to_async(instance.refresh_from_db)()
    assert instance.metadata["human_handoff_dispatch"]["owner_mutated"] is False


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
    assert instance.state == ConversationInstance.State.FAILED_RETRYABLE
    successful_retry = AsyncMock(return_value={"updated": True})
    with patch(
        "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
        new=successful_retry,
    ):
        replayed = await sync_to_async(resume_pending_ticket_effect)(instance)

    assert replayed is not None
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_handoff_safe_suppression_is_terminal_without_route_or_retry() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Vou transferir.",
        sources=[],
        requires_human_handoff=True,
        handoff_reason="Customer explicitly requested human assistance.",
        agent_trace=[],
        tokens_used=0,
        model_name="handoff_policy",
        latency_ms=1,
        decision=SupervisorDecision(
            outcome="escalate_human",
            final_response="Vou transferir.",
            confidence=1.0,
        ),
    )
    route_handoff = AsyncMock(return_value={"updated": True})

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(
                return_value={
                    "sent": False,
                    "suppressed": True,
                    "retryable": False,
                    "reason": "human_agent_participating",
                }
            ),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=route_handoff,
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Quero falar com um humano",
            result=result,
        )

    route_handoff.assert_not_awaited()
    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.IGNORED
    assert instance.failure_count == 0
    assert instance.next_retry_at is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_human_takeover_after_handoff_confirmation_never_reroutes_ticket() -> None:
    instance = await sync_to_async(_instance)()
    result = SalomaoResponse(
        session_id="hubspot-ticket-ticket-1",
        message="Vou transferir.",
        sources=[],
        requires_human_handoff=True,
        handoff_reason="Customer explicitly requested human assistance.",
        agent_trace=[],
        tokens_used=0,
        model_name="handoff_policy",
        latency_ms=1,
        decision=SupervisorDecision(
            outcome="escalate_human",
            final_response="Vou transferir.",
            confidence=1.0,
        ),
    )

    with (
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "out-handoff"}),
        ),
        patch(
            "apps.ai_agents.services.hubspot.update_hubspot_ticket_route",
            new=AsyncMock(
                return_value={
                    "updated": False,
                    "suppressed": True,
                    "retryable": False,
                    "reason": "ticket_owned_by_human",
                }
            ),
        ),
    ):
        await apply_supervisor_result(
            instance=instance,
            context={"thread_ids": ["thread-1"]},
            conversation_context=_context(),
            message="Quero falar com um humano",
            result=result,
        )

    await sync_to_async(instance.refresh_from_db)()
    assert instance.state == ConversationInstance.State.IGNORED
    assert instance.failure_count == 0
    assert instance.metadata["human_handoff_dispatch"]["suppressed"] is True


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
