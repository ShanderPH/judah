"""Tests for Salomão chat API response and error classification."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from apps.ai_agents.agents.supervisor import SalomaoResponse
from apps.ai_agents.api.routers import ChatRequest, chat_with_salomao
from common.exceptions import ExternalServiceError


def _request():
    return SimpleNamespace(
        auth=SimpleNamespace(
            pk=7,
            username="user",
            email="user@example.com",
            first_name="Ana",
            last_name="Silva",
            church_id="church",
        )
    )


def _result() -> SalomaoResponse:
    return SalomaoResponse(
        session_id="user-7",
        message="Resposta",
        sources=[{"title": "Fonte"}],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=["ok"],
        tokens_used=10,
        model_name="model",
        latency_ms=5,
    )


@pytest.mark.asyncio
async def test_chat_success() -> None:
    supervisor = SimpleNamespace(run_pipeline_async=AsyncMock(return_value=_result()))
    with patch("apps.ai_agents.api.routers.SalomaoSupervisorAgent", return_value=supervisor) as factory:
        status, response = await chat_with_salomao(_request(), ChatRequest(message="Olá"))

    assert status == 200
    assert response.message == "Resposta"
    assert factory.call_args.kwargs["session_id"] == "user-7"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "error_code"),
    [
        (TimeoutError("slow"), "AGENT_TIMEOUT"),
        (RuntimeError("request timed out"), "AGENT_TIMEOUT"),
        (RuntimeError("rate limit reached"), "RATE_LIMIT"),
        (RuntimeError("insufficient_quota"), "RATE_LIMIT"),
    ],
)
async def test_chat_maps_provider_failures(error: Exception, error_code: str) -> None:
    supervisor = SimpleNamespace(run_pipeline_async=AsyncMock(side_effect=error))
    with patch("apps.ai_agents.api.routers.SalomaoSupervisorAgent", return_value=supervisor):
        status, response = await chat_with_salomao(_request(), ChatRequest(message="Olá"))
    assert status == 503
    assert response.error_code == error_code


@pytest.mark.asyncio
async def test_chat_wraps_initialization_and_unexpected_failures() -> None:
    with (
        patch("apps.ai_agents.api.routers.SalomaoSupervisorAgent", side_effect=RuntimeError("init")),
        pytest.raises(ExternalServiceError),
    ):
        await chat_with_salomao(_request(), ChatRequest(message="Olá"))

    supervisor = SimpleNamespace(run_pipeline_async=AsyncMock(side_effect=RuntimeError("unexpected")))
    with (
        patch("apps.ai_agents.api.routers.SalomaoSupervisorAgent", return_value=supervisor),
        pytest.raises(ExternalServiceError),
    ):
        await chat_with_salomao(_request(), ChatRequest(message="Olá"))
