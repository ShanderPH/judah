"""Tests for the Salomao v1 HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from apps.integrations.salomao_v1 import SalomaoV1Client
from common.exceptions import ExternalServiceError


@pytest.mark.asyncio
async def test_chat_posts_to_salomao_v1_chat_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat"
        assert request.method == "POST"
        assert request.headers["content-type"] == "application/json"
        assert request.content == b'{"message":"Como crio um evento?","session_id":"user-7"}'
        return httpx.Response(
            200,
            json={
                "success": True,
                "response": "Abra o modulo Eventos e clique em criar.",
                "session_id": "user-7",
                "transfer_requested": False,
                "model_used": "gpt-4o",
                "tokens": {"prompt": 10, "completion": 20, "total": 30},
            },
        )

    client = SalomaoV1Client(
        base_url="http://salomao.local",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.chat(message="Como crio um evento?", session_id="user-7")

    assert result.response == "Abra o modulo Eventos e clique em criar."
    assert result.session_id == "user-7"
    assert result.tokens.total == 30


@pytest.mark.asyncio
async def test_chat_maps_failed_response_to_external_service_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": False,
                "response": "",
                "session_id": "user-7",
                "error": "falha no agente",
            },
        )

    client = SalomaoV1Client(
        base_url="http://salomao.local",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ExternalServiceError, match="falha no agente"):
        await client.chat(message="oi", session_id="user-7")


@pytest.mark.asyncio
async def test_chat_retries_transient_provider_failure(settings, monkeypatch) -> None:
    settings.SALOMAO_V1_MAX_ATTEMPTS = 3
    sleep = AsyncMock()
    monkeypatch.setattr("apps.integrations.salomao_v1.client.asyncio.sleep", sleep)
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(
            200,
            json={
                "success": True,
                "response": "Consegui responder após a recuperação do serviço.",
                "session_id": "user-7",
            },
        )

    client = SalomaoV1Client(
        base_url="http://salomao.local",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.chat(message="oi", session_id="user-7")

    assert attempts == 2
    sleep.assert_awaited_once_with(0.25)
    assert result.response.startswith("Consegui responder")
