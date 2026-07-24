"""Extended tests for HubSpot AI worker helpers and endpoint routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from django.test import override_settings

from apps.ai_agents.agents.supervisor import SalomaoResponse
from apps.ai_agents.api import webhooks
from apps.ai_agents.models import ConversationInstance, TokenTrackingLog


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
    fallback_context = {
        "ticket_id": "1",
        "subject": "Assunto",
        "originating_channel": "chat",
        "content": "Conteúdo",
    }
    assert "Ticket HubSpot #1" in webhooks._build_hubspot_supervisor_message(fallback_context, "1")
    assert webhooks._build_hubspot_supervisor_message({}, None) is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_token_tracking_success_and_best_effort_failure() -> None:
    await webhooks._persist_token_tracking(
        session_id="session",
        ticket_id="ticket",
        model_name="",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.01,
    )
    assert await TokenTrackingLog.objects.filter(session_id="session", model_name="unknown").aexists()

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
            require_incoming=True,
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


@pytest.mark.asyncio
async def test_pipeline_wrappers_success_and_failure() -> None:
    with (
        patch("apps.ai_agents.api.webhooks.hydrate_ticket_context", new=AsyncMock(return_value={"subject": "A"})),
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

    thread_context = {"ticket_id": "ticket-2", "conversation_history": [{"direction": "INCOMING", "text": "Oi"}]}
    with (
        patch("apps.ai_agents.api.webhooks.hydrate_thread_context", new=AsyncMock(return_value=thread_context)),
        patch("apps.ai_agents.api.webhooks.off_hours_reason", return_value="off_hours"),
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(),
        ) as run,
    ):
        await webhooks._run_salomao_v1_thread_pipeline("thread-1")
    assert run.await_args.kwargs["require_incoming"] is True
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
    }
    with (
        override_settings(HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline"),
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
async def test_thread_pipeline_skips_when_latest_message_is_outgoing() -> None:
    instance = Mock()
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
            return_value=instance,
        ),
        patch(
            "apps.ai_agents.api.webhooks._prepare_instance_for_supervisor",
            new=AsyncMock(),
        ),
        patch(
            "apps.ai_agents.api.webhooks._resume_waiting_instance_for_customer_message",
            new=AsyncMock(),
        ) as resume,
        patch("apps.ai_agents.api.webhooks.SalomaoSupervisorAgent") as supervisor,
    ):
        await webhooks._run_supervisor_for_hubspot_context(
            context,
            session_id="session-1",
            ticket_id="ticket-1",
            require_incoming=True,
        )

    supervisor.assert_not_called()
    resume.assert_not_awaited()


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
