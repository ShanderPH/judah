"""Extended tests for HubSpot AI worker helpers and endpoint routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from apps.ai_agents.agents.supervisor import SalomaoResponse
from apps.ai_agents.api import webhooks
from apps.ai_agents.models import ConversationInstance, TokenTrackingLog, ToolCallAuditLog
from apps.ai_agents.services.service_cycles import ensure_current_service_cycle


def _response() -> SalomaoResponse:
    return SalomaoResponse(
        session_id="session",
        message="Resposta",
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["ok"],
        tokens_used=15,
        prompt_tokens=10,
        completion_tokens=5,
        model_name="gpt-4o-mini",
        latency_ms=10,
    )


def test_signature_helpers_extract_ticket_and_build_messages() -> None:
    request = Mock()
    with (
        patch("apps.ai_agents.api.webhooks.verify_hubspot_signature_v1", return_value=True),
        patch("apps.ai_agents.api.webhooks.verify_hubspot_signature_v3", return_value=True),
    ):
        assert webhooks._verify_signature_v1(request, "secret") is True
        assert webhooks._verify_signature_v3(request, "secret") is True

    assert webhooks._extract_ticket_id([{"x": 1}, {"objectId": 42}]) == "42"
    assert webhooks._extract_ticket_id({"objectId": "1"}) == "1"
    assert webhooks._extract_ticket_id({}) is None

    context = {
        "ticket_id": "1",
        "subject": "Assunto",
        "originating_channel": "chat",
        "conversation_history": [
            {"direction": "OUTGOING", "text": "Olá"},
            {"direction": "INCOMING", "text": " Preciso de ajuda\x00 "},
        ],
    }
    assert webhooks._latest_incoming_customer_text(context) == "Preciso de ajuda\x00"
    safe, flags = webhooks._sanitize_latest_incoming_customer_text(context)
    assert safe is not context
    assert safe["conversation_history"][-1]["text"] == "Preciso de ajuda"
    assert flags == ()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_token_tracking_success_and_best_effort_failure() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:token-cycle",
        hubspot_thread_id="token-cycle",
    )
    cycle = await sync_to_async(ensure_current_service_cycle)(instance)
    await webhooks._persist_token_tracking(
        session_id="session",
        ticket_id="ticket",
        model_name="",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.01,
        service_cycle_id=str(cycle.pk),
    )
    assert await TokenTrackingLog.objects.filter(
        session_id="session",
        model_name="unknown",
        service_cycle=cycle,
    ).aexists()

    with patch("apps.ai_agents.api.webhooks._persist_token_tracking", new=AsyncMock()) as persist:
        await webhooks._record_usage("ticket", "session", _response())
    persist.assert_awaited_once()

    with patch(
        "apps.ai_agents.api.webhooks._persist_token_tracking",
        new=AsyncMock(side_effect=RuntimeError("db")),
    ):
        await webhooks._record_usage("ticket", "session", _response())


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_prepare_retryable_instance_and_mark_pipeline_failure() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:ticket:prepare",
        hubspot_ticket_id="prepare",
        state=ConversationInstance.State.FAILED_RETRYABLE,
    )
    await webhooks._prepare_instance_for_supervisor(instance)
    await instance.arefresh_from_db()
    assert instance.state == ConversationInstance.State.CONTEXT_HYDRATING

    active = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:failure",
        hubspot_thread_id="failure",
        state=ConversationInstance.State.CONTEXT_HYDRATING,
    )
    await webhooks._mark_pipeline_failure(thread_id="failure", error=RuntimeError("offline"))
    await active.arefresh_from_db()
    assert active.state == ConversationInstance.State.FAILED_RETRYABLE

    with patch("apps.ai_agents.api.webhooks.mark_retryable_failure") as mark:
        await webhooks._mark_pipeline_failure(thread_id="missing", error=RuntimeError("offline"))
    mark.assert_not_called()

    terminal = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:terminal-failure",
        hubspot_thread_id="terminal-failure",
        state=ConversationInstance.State.CLOSED,
    )
    await webhooks._mark_pipeline_failure(
        thread_id="terminal-failure",
        error=RuntimeError("original pipeline error"),
    )
    await terminal.arefresh_from_db()
    assert terminal.state == ConversationInstance.State.CLOSED
    assert terminal.failure_count == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_verified_provider_route_reopens_stale_human_lifecycle() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:verified-human-reentry",
        hubspot_thread_id="verified-human-reentry",
        state=ConversationInstance.State.HUMAN_IN_PROGRESS,
        assigned_agent_id="former-owner",
    )

    await webhooks._prepare_instance_for_supervisor(
        instance,
        allow_verified_route_reopen=True,
    )

    await instance.arefresh_from_db()
    assert instance.state == ConversationInstance.State.CONTEXT_HYDRATING
    assert instance.assigned_agent_id is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_customer_message_resumes_waiting_instance() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:ticket:waiting",
        hubspot_ticket_id="waiting",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
    )

    await webhooks._resume_waiting_instance_for_customer_message(instance)

    await instance.arefresh_from_db()
    assert instance.state == ConversationInstance.State.CONTEXT_HYDRATING


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_waiting_conversation_processes_and_sends_next_customer_turn() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:resumed-turn",
        hubspot_thread_id="resumed-turn",
        hubspot_ticket_id="ticket-resumed-turn",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
    )
    sibling = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:sibling-turn",
        hubspot_thread_id="sibling-turn",
        hubspot_ticket_id="ticket-resumed-turn",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
    )
    context = {
        "ticket_id": "ticket-resumed-turn",
        "originating_channel": "chat",
        "thread_ids": ["resumed-turn"],
        "conversation_history": [
            {"id": "customer-message-2", "direction": "INCOMING", "text": "Tenho outra dúvida"},
        ],
    }
    supervisor_instance = Mock()
    supervisor_instance.run_pipeline_async = AsyncMock(return_value=_response())

    with (
        patch(
            "apps.ai_agents.api.webhooks.handle_protocol_lookup_from_hubspot_context",
            new=AsyncMock(return_value=None),
        ),
        patch("apps.ai_agents.api.webhooks.SalomaoSupervisorAgent", return_value=supervisor_instance),
        patch("apps.ai_agents.api.webhooks._record_usage", new=AsyncMock()),
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "reply-2"}),
        ) as send_reply,
    ):
        await webhooks._run_supervisor_for_hubspot_context(
            context,
            session_id="hubspot-thread-resumed-turn",
            ticket_id="ticket-resumed-turn",
        )

    send_reply.assert_awaited_once()
    await instance.arefresh_from_db()
    await sibling.arefresh_from_db()
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert instance.failure_count == 0
    assert sibling.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert await sibling.state_transitions.acount() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_verified_ai_route_reopens_closed_thread_and_replies() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:closed-reopen",
        hubspot_thread_id="closed-reopen",
        hubspot_ticket_id="ticket-closed-reopen",
        state=ConversationInstance.State.CLOSED,
        last_message_id="previous-message",
    )
    context = {
        "ticket_id": "ticket-closed-reopen",
        "subject": "Novo atendimento",
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "",
        "originating_channel": "chat",
        "thread_ids": ["closed-reopen"],
        "conversation_history": [
            {
                "id": "new-customer-message",
                "thread_id": "closed-reopen",
                "direction": "INCOMING",
                "text": "Preciso de ajuda novamente",
            },
        ],
    }
    supervisor = Mock()
    supervisor.run_pipeline_async = AsyncMock(return_value=_response())

    with (
        override_settings(
            HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
            HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
        ),
        patch(
            "apps.ai_agents.api.webhooks.hydrate_ticket_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks.handle_protocol_lookup_from_hubspot_context",
            new=AsyncMock(return_value=None),
        ),
        patch("apps.ai_agents.api.webhooks.SalomaoSupervisorAgent", return_value=supervisor),
        patch("apps.ai_agents.api.webhooks._record_usage", new=AsyncMock()),
        patch(
            "apps.ai_agents.services.hubspot.send_salomao_reply_to_hubspot_thread",
            new=AsyncMock(return_value={"sent": True, "message_id": "reply-reopened"}),
        ) as send_reply,
    ):
        await webhooks._run_supervisor_pipeline("ticket-closed-reopen")

    send_reply.assert_awaited_once()
    await instance.arefresh_from_db()
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert instance.closed_at is None
    assert instance.failure_count == 0
    assert await instance.state_transitions.filter(
        from_state=ConversationInstance.State.CLOSED,
        to_state=ConversationInstance.State.CONTEXT_HYDRATING,
    ).aexists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_closed_thread_does_not_reprocess_an_answered_customer_turn() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:closed-answered",
        hubspot_thread_id="closed-answered",
        hubspot_ticket_id="ticket-closed-answered",
        state=ConversationInstance.State.CLOSED,
        last_message_id="answered-message",
    )
    await ToolCallAuditLog.objects.acreate(
        instance=instance,
        tool_name="send_thread_reply",
        idempotency_key=f"reply:{instance.pk}:answered-message",
        status=ToolCallAuditLog.Status.SUCCEEDED,
    )
    context = {
        "ticket_id": "ticket-closed-answered",
        "subject": "Atendimento concluído",
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "",
        "originating_channel": "chat",
        "thread_ids": ["closed-answered"],
        "conversation_history": [
            {
                "id": "answered-message",
                "thread_id": "closed-answered",
                "direction": "INCOMING",
                "text": "Mensagem já respondida",
            },
        ],
    }

    with (
        override_settings(
            HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
            HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
        ),
        patch(
            "apps.ai_agents.api.webhooks.hydrate_ticket_context",
            new=AsyncMock(return_value=context),
        ),
        patch("apps.ai_agents.api.webhooks.SalomaoSupervisorAgent") as supervisor,
    ):
        await webhooks._run_supervisor_pipeline("ticket-closed-answered")

    supervisor.assert_not_called()
    await instance.arefresh_from_db()
    assert instance.state == ConversationInstance.State.CLOSED
    assert await instance.state_transitions.acount() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pipeline_failure_is_recorded_only_on_the_target_thread() -> None:
    first = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:failure-first",
        hubspot_thread_id="failure-first",
        hubspot_ticket_id="ticket-shared-failure",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
    )
    second = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:failure-second",
        hubspot_thread_id="failure-second",
        hubspot_ticket_id="ticket-shared-failure",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
    )

    await webhooks._mark_pipeline_failure(
        ticket_id="ticket-shared-failure",
        thread_id="failure-second",
        error=RuntimeError("targeted failure"),
    )

    await first.arefresh_from_db()
    await second.arefresh_from_db()
    assert first.state == ConversationInstance.State.AI_SERVICE_RUNNING
    assert first.failure_count == 0
    assert second.state == ConversationInstance.State.FAILED_RETRYABLE
    assert second.failure_count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_terminal_instance_does_not_mask_original_pipeline_error() -> None:
    await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:terminal-original-error",
        hubspot_thread_id="terminal-original-error",
        hubspot_ticket_id="ticket-terminal-original-error",
        state=ConversationInstance.State.CLOSED,
    )
    context = {
        "ticket_id": "ticket-terminal-original-error",
        "subject": "Erro original",
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "",
        "thread_ids": ["terminal-original-error"],
        "conversation_history": [
            {
                "id": "new-message",
                "thread_id": "terminal-original-error",
                "direction": "INCOMING",
                "text": "Nova mensagem",
            },
        ],
    }

    with (
        override_settings(
            HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
            HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
        ),
        patch(
            "apps.ai_agents.api.webhooks.hydrate_ticket_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(side_effect=RuntimeError("original pipeline error")),
        ),
        pytest.raises(RuntimeError, match="original pipeline error"),
    ):
        await webhooks._run_supervisor_pipeline("ticket-terminal-original-error")


@pytest.mark.asyncio
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
    HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
)
async def test_pipeline_wrappers_success_and_failure() -> None:
    with (
        patch(
            "apps.ai_agents.api.webhooks.hydrate_ticket_context",
            new=AsyncMock(
                return_value={
                    "subject": "A",
                    "pipeline": "ai-pipeline",
                    "pipeline_stage": "ai-stage",
                    "owner_id": "",
                }
            ),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(),
        ) as run,
    ):
        await webhooks._run_supervisor_pipeline("ticket-1", is_off_hours=True)
    run.assert_awaited_once()

    with (
        patch(
            "apps.ai_agents.api.webhooks.hydrate_ticket_context",
            new=AsyncMock(return_value={"errors": ["offline"]}),
        ),
        patch("apps.ai_agents.api.webhooks._mark_pipeline_failure", new=AsyncMock()) as mark,
        pytest.raises(RuntimeError),
    ):
        await webhooks._run_supervisor_pipeline("ticket-1")
    mark.assert_awaited_once()

    thread_context = {
        "ticket_id": "ticket-2",
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "",
        "conversation_history": [{"direction": "INCOMING", "text": "Oi"}],
    }
    with (
        patch("apps.ai_agents.api.webhooks.hydrate_thread_context", new=AsyncMock(return_value=thread_context)),
        patch("apps.ai_agents.api.webhooks.off_hours_reason", return_value="off_hours"),
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(),
        ) as run,
    ):
        await webhooks._run_salomao_v1_thread_pipeline("thread-1")
    assert run.await_args.kwargs["session_id"] == "hubspot-thread-thread-1"
    assert run.await_args.kwargs["is_off_hours"] is True

    with (
        patch(
            "apps.ai_agents.api.webhooks.hydrate_thread_context",
            new=AsyncMock(return_value={"errors": ["offline"]}),
        ),
        patch("apps.ai_agents.api.webhooks._mark_pipeline_failure", new=AsyncMock()) as mark,
        pytest.raises(RuntimeError),
    ):
        await webhooks._run_salomao_v1_thread_pipeline("thread-1")
    mark.assert_awaited_once()


@pytest.mark.asyncio
async def test_ticket_pipeline_enforcement_skips_non_ai_pipeline() -> None:
    context = {
        "subject": "A",
        "pipeline": "support-pipeline",
        "pipeline_stage": "ai-stage",
    }
    with (
        override_settings(
            HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
            HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
        ),
        patch(
            "apps.ai_agents.api.webhooks.hydrate_ticket_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(),
        ) as run,
    ):
        await webhooks._run_supervisor_pipeline(
            "ticket-1",
            enforce_ai_pipeline=True,
        )

    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_thread_pipeline_skips_ticket_owned_by_human() -> None:
    context = {
        "ticket_id": "ticket-1",
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "human-owner",
        "conversation_history": [{"direction": "INCOMING", "text": "Aguardando"}],
    }
    with (
        override_settings(
            HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
            HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
        ),
        patch(
            "apps.ai_agents.api.webhooks.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(),
        ) as run,
    ):
        await webhooks._run_salomao_v1_thread_pipeline("thread-1")

    run.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_thread_retry_resumes_pending_effect_without_model() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:thread-effect",
        hubspot_thread_id="thread-effect",
        hubspot_ticket_id="ticket-effect",
        state=ConversationInstance.State.FAILED_RETRYABLE,
    )
    await ToolCallAuditLog.objects.acreate(
        instance=instance,
        tool_name="update_ticket_stage",
        input={"ticket_id": "ticket-effect", "stage_id": "closed"},
        status=ToolCallAuditLog.Status.FAILED,
        idempotency_key="ai-resolution-close:v1:thread-effect",
    )
    context = {
        "ticket_id": "ticket-effect",
        "thread_ids": ["thread-effect"],
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "",
        "conversation_history": [
            {
                "direction": "OUTGOING",
                "text": "Resposta já entregue",
                "senders": [{"actorId": "A-salomao"}],
            }
        ],
    }

    with (
        override_settings(
            HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
            HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
            HUBSPOT_SALOMAO_SENDER_ACTOR_ID="A-salomao",
        ),
        patch(
            "apps.ai_agents.api.webhooks.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks.resume_pending_ticket_effect",
            return_value={"closed": True},
        ) as resume,
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(),
        ) as run,
    ):
        await webhooks._run_salomao_v1_thread_pipeline("thread-effect")

    resume.assert_called_once()
    run.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ticket_retry_replays_placeholder_effect_not_thread_instance() -> None:
    placeholder = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:ticket:placeholder-effect",
        hubspot_ticket_id="placeholder-effect",
        state=ConversationInstance.State.FAILED_RETRYABLE,
    )
    await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:placeholder-effect-thread",
        hubspot_thread_id="placeholder-effect-thread",
        hubspot_ticket_id="placeholder-effect",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
    )
    await ToolCallAuditLog.objects.acreate(
        instance=placeholder,
        tool_name="update_ticket_stage",
        input={"ticket_id": "placeholder-effect", "stage_id": "closed"},
        status=ToolCallAuditLog.Status.FAILED,
        idempotency_key="ai-resolution-close:v1:placeholder-effect",
    )
    context = {
        "ticket_id": "placeholder-effect",
        "thread_ids": ["placeholder-effect-thread"],
    }

    with patch(
        "apps.ai_agents.api.webhooks.resume_pending_ticket_effect",
        return_value={"closed": True},
    ) as resume:
        resumed = await webhooks._resume_pending_effect_for_context(
            context,
            ticket_id="placeholder-effect",
            source_instance_id=str(placeholder.pk),
        )

    assert resumed is True
    resume.assert_called_once_with(placeholder)


@pytest.mark.asyncio
async def test_thread_pipeline_skips_when_latest_message_is_outgoing() -> None:
    context = {
        "ticket_id": "ticket-1",
        "thread_ids": ["thread-1"],
        "conversation_history": [
            {"direction": "INCOMING", "text": "Preciso de ajuda"},
            {"direction": "OUTGOING", "text": "Como posso ajudar?"},
        ],
    }
    with (
        patch(
            "apps.ai_agents.api.webhooks.ensure_conversation_instance",
        ) as ensure_instance,
        patch(
            "apps.ai_agents.api.webhooks._suppress_stale_processing_instance",
            new=AsyncMock(),
        ) as suppress_stale,
        patch("apps.ai_agents.api.webhooks.SalomaoSupervisorAgent") as supervisor,
    ):
        await webhooks._run_supervisor_for_hubspot_context(
            context,
            session_id="session-1",
            ticket_id="ticket-1",
        )

    supervisor.assert_not_called()
    ensure_instance.assert_not_called()
    suppress_stale.assert_awaited_once_with(
        context,
        ticket_id="ticket-1",
        source_instance_id=None,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_directionless_outgoing_verification_never_terminalizes_active_run() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:outgoing-neutral",
        hubspot_thread_id="outgoing-neutral",
        hubspot_ticket_id="ticket-outgoing-neutral",
        state=ConversationInstance.State.AI_SERVICE_RUNNING,
    )
    context = {
        "ticket_id": "ticket-outgoing-neutral",
        "thread_ids": ["outgoing-neutral"],
        "conversation_history": [
            {"id": "incoming-1", "direction": "INCOMING", "text": "Preciso de ajuda"},
            {"id": "outgoing-1", "direction": "OUTGOING", "text": "Resposta já entregue"},
        ],
    }

    await webhooks._run_supervisor_for_hubspot_context(
        context,
        session_id="hubspot-thread-outgoing-neutral",
        ticket_id="ticket-outgoing-neutral",
    )

    await instance.arefresh_from_db()
    assert instance.state == ConversationInstance.State.AI_SERVICE_RUNNING
    assert "ai_reply_suppressed" not in instance.metadata


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stale_ticket_retry_is_terminalized_before_model_execution() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:ticket:stale-retry",
        hubspot_ticket_id="stale-retry",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=1,
    )
    thread_instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:stale-retry-thread",
        hubspot_thread_id="stale-retry-thread",
        hubspot_ticket_id="stale-retry",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
    )
    context = {
        "ticket_id": "stale-retry",
        "thread_ids": ["stale-retry-thread"],
        "conversation_history": [
            {"id": "incoming-1", "direction": "INCOMING", "text": "Preciso de ajuda"},
            {"id": "outgoing-1", "direction": "OUTGOING", "text": "Resposta já entregue"},
        ],
    }

    with patch("apps.ai_agents.api.webhooks.SalomaoSupervisorAgent") as supervisor:
        await webhooks._run_supervisor_for_hubspot_context(
            context,
            session_id="hubspot-ticket-stale-retry",
            ticket_id="stale-retry",
            source_instance_id=str(instance.pk),
        )

    await instance.arefresh_from_db()
    await thread_instance.arefresh_from_db()
    assert instance.state == ConversationInstance.State.IGNORED
    assert instance.failure_count == 1
    assert instance.metadata["ai_reply_suppressed"]["reason"] == "no_current_customer_turn"
    assert thread_instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER
    assert await thread_instance.state_transitions.acount() == 0
    supervisor.assert_not_called()


@pytest.mark.asyncio
async def test_ticket_change_endpoint_routes_all_outcomes() -> None:
    request = SimpleNamespace(headers={})

    with patch("apps.ai_agents.api.webhooks._signature_ok", return_value=False):
        status, body = await webhooks.hubspot_ticket_change(request, [{"objectId": "1"}])
    assert status == 401
    assert body.error_code == "INVALID_SIGNATURE"

    with patch("apps.ai_agents.api.webhooks._signature_ok", return_value=True):
        status, body = await webhooks.hubspot_ticket_change(request, [{}])
    assert status == 422
    assert body.error_code == "MISSING_TICKET_ID"

    with (
        patch("apps.ai_agents.api.webhooks._signature_ok", return_value=True),
        override_settings(AI_ROUTING_ENABLED=False),
    ):
        status, body = await webhooks.hubspot_ticket_change(request, [{"objectId": "1"}])
    assert status == 202
    assert body.routed_to == "noop"

    with (
        patch("apps.ai_agents.api.webhooks._signature_ok", return_value=True),
        patch("apps.ai_agents.api.webhooks.off_hours_reason", return_value="outside"),
        patch("apps.ai_agents.api.webhooks.is_quinta_fire", return_value=False),
        patch("apps.ai_agents.api.webhooks.is_business_hours", return_value=False),
        patch("apps.ai_agents.api.webhooks.run_supervisor_pipeline_task.delay") as delay,
        override_settings(AI_ROUTING_ENABLED=True),
    ):
        status, body = await webhooks.hubspot_ticket_change(request, [{"objectId": "1"}])
    assert status == 202
    assert body.routed_to == "supervisor_pipeline"
    delay.assert_called_once_with("1", True)


def test_signature_policy_mock_debug_secret_and_validation() -> None:
    request = Mock()
    with patch("apps.ai_agents.api.webhooks.USE_MOCK_HUBSPOT", True):
        assert webhooks._signature_ok(request) is True

    with (
        patch("apps.ai_agents.api.webhooks.USE_MOCK_HUBSPOT", False),
        override_settings(HUBSPOT_APP_SECRET="", DEBUG=False),
    ):
        assert webhooks._signature_ok(request) is False

    with (
        patch("apps.ai_agents.api.webhooks.USE_MOCK_HUBSPOT", False),
        patch("apps.ai_agents.api.webhooks.is_valid_hubspot_request", return_value=True) as valid,
        override_settings(HUBSPOT_APP_SECRET="secret", DEBUG=False),
    ):
        assert webhooks._signature_ok(request) is True
    valid.assert_called_once_with(request, "secret")
