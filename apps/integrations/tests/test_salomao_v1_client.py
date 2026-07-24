"""Tests for the Salomao v1 HTTP client."""

from __future__ import annotations

import httpx
import pytest
from django.test import override_settings

from apps.integrations.salomao_v1 import SalomaoV1Client
from apps.integrations.salomao_v1 import client as salomao_client_module
from apps.integrations.salomao_v1.client import (
    is_salomao_v1_configured,
    is_salomao_v1_provider_error,
    send_chat_to_salomao_v1,
)
from common.exceptions import ExternalServiceError


@pytest.fixture(autouse=True)
def _reset_salomao_circuit_breaker() -> None:
    salomao_client_module._circuit_breaker._on_success()


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


@override_settings(SALOMAO_V1_BASE_URL=" https://salomao.example ")
def test_configuration_and_provider_error_detection() -> None:
    assert is_salomao_v1_configured() is True
    assert is_salomao_v1_provider_error(None) is False
    assert is_salomao_v1_provider_error("Incorrect API key provided") is True
    assert is_salomao_v1_provider_error("Resposta normal") is False


def test_client_requires_base_url() -> None:
    with pytest.raises(ExternalServiceError):
        SalomaoV1Client(base_url="")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (
            lambda request: httpx.Response(500, text="provider failed"),
            "returned HTTP 500",
        ),
        (
            lambda request: httpx.Response(200, content=b"not-json"),
            "invalid JSON",
        ),
        (
            lambda request: httpx.Response(
                200,
                json={
                    "success": True,
                    "response": "insufficient_quota",
                    "session_id": "s",
                },
            ),
            "credential or quota",
        ),
    ],
)
async def test_chat_maps_http_json_and_provider_errors(handler, message: str) -> None:
    client = SalomaoV1Client(base_url="https://salomao.local", transport=httpx.MockTransport(handler))
    with pytest.raises(ExternalServiceError, match=message):
        await client.chat(message="oi", session_id="s")


@pytest.mark.asyncio
async def test_chat_maps_timeout_and_transport_errors() -> None:
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = SalomaoV1Client(base_url="https://salomao.local", transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(TimeoutError):
        await client.chat(message="oi", session_id="s")
    salomao_client_module._circuit_breaker._on_success()

    async def transport_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = SalomaoV1Client(base_url="https://salomao.local", transport=httpx.MockTransport(transport_handler))
    with pytest.raises(ExternalServiceError, match="Could not reach"):
        await client.chat(message="oi", session_id="s")


@pytest.mark.asyncio
async def test_chat_sends_image_audio_and_wrapper(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "image_base64" in body
        assert "image/jpeg" in body
        assert "audio_base64" in body
        assert "wav" in body
        return httpx.Response(200, json={"success": True, "response": "ok", "session_id": "s"})

    client = SalomaoV1Client(base_url="https://salomao.local", transport=httpx.MockTransport(handler))
    result = await client.chat(
        message="oi",
        session_id="s",
        image_base64="image",
        audio_base64="audio",
    )
    assert result.response == "ok"

    monkeypatch.setattr(
        "apps.integrations.salomao_v1.client.SalomaoV1Client",
        lambda: client,
    )
    assert (
        await send_chat_to_salomao_v1(
            message="oi",
            session_id="s",
            image_base64="image",
            audio_base64="audio",
        )
    ).response == "ok"
