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
        patch(
            "apps.ai_agents.api.webhooks._run_supervisor_for_hubspot_context",
            new=AsyncMock(),
        ) as run,
    ):
        await webhooks._run_salomao_v1_thread_pipeline("thread-1")
    assert run.await_args.kwargs["require_incoming"] is True

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
