"""Tests for HubSpot chat context used by the Salomao v1 adapter."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from django.test import override_settings

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services import hubspot
from apps.ai_agents.services.hubspot import (
    _auth_headers,
    _download_image_attachment,
    _fetch_conversation_history,
    _image_mime_type,
    _is_allowed_attachment_url,
    _latest_incoming_image_attachment,
    _recipient_from_sender,
    _resolve_attachment_url,
    build_conversation_context_from_hubspot_context,
    build_salomao_prompt_from_hubspot_context,
    create_hubspot_thread_comment,
    evaluate_salomao_ticket_eligibility,
    hydrate_thread_context,
    hydrate_ticket_context,
    send_salomao_reply_to_hubspot_thread,
    update_hubspot_ticket_route,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"image-content"


def _async_client_context(client: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
    HUBSPOT_N1_NEW_STAGE_ID="ai-active",
    HUBSPOT_SALOMAO_SENDER_ACTOR_ID="A-salomao",
)
@pytest.mark.parametrize(
    ("context", "eligible", "reason"),
    [
        (
            {
                "pipeline": "ai-pipeline",
                "pipeline_stage": "ai-active",
                "owner_id": "",
                "conversation_history": [],
            },
            True,
            "eligible",
        ),
        (
            {
                "pipeline": "support-pipeline",
                "pipeline_stage": "ai-active",
                "owner_id": "",
                "conversation_history": [],
            },
            False,
            "ticket_left_ai_pipeline",
        ),
        (
            {
                "pipeline": "ai-pipeline",
                "pipeline_stage": "waiting",
                "owner_id": "",
                "conversation_history": [],
            },
            False,
            "ticket_left_ai_stage",
        ),
        (
            {
                "pipeline": "ai-pipeline",
                "pipeline_stage": "ai-active",
                "owner_id": "human-owner",
                "conversation_history": [],
            },
            False,
            "ticket_owned_by_human",
        ),
        (
            {
                "pipeline": "ai-pipeline",
                "pipeline_stage": "ai-active",
                "owner_id": "",
                "conversation_history": [
                    {
                        "id": "human-before-customer",
                        "direction": "OUTGOING",
                        "created_at": "2026-07-28T23:55:41Z",
                        "senders": [{"actorId": "A-human", "actorType": "AGENT"}],
                    },
                    {
                        "id": "customer-after-human",
                        "direction": "INCOMING",
                        "text": "Quero falar com um atendente",
                        "created_at": "2026-07-28T23:56:25Z",
                        "senders": [{"actorId": "visitor"}],
                    },
                ],
            },
            True,
            "eligible",
        ),
        (
            {
                "pipeline": "ai-pipeline",
                "pipeline_stage": "ai-active",
                "owner_id": "",
                "conversation_history": [
                    {
                        "id": "customer-before-human",
                        "direction": "INCOMING",
                        "created_at": "2026-07-28T23:55:25Z",
                        "senders": [{"actorId": "visitor"}],
                    },
                    {
                        "id": "human-after-customer",
                        "direction": "OUTGOING",
                        "created_at": "2026-07-28T23:55:41Z",
                        "senders": [{"actorId": "A-human", "actorType": "AGENT"}],
                    },
                ],
            },
            False,
            "human_agent_participating",
        ),
    ],
)
def test_salomao_ticket_eligibility_is_exclusive(
    context: dict[str, object],
    eligible: bool,
    reason: str,
) -> None:
    result = evaluate_salomao_ticket_eligibility(context)

    assert result["eligible"] is eligible
    assert result["reason"] == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_id", ["ai-owner", ""])
async def test_update_ticket_route_sets_pipeline_stage_and_owner(monkeypatch, owner_id: str) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    response = MagicMock()
    response.status_code = 200
    client = MagicMock()
    client.patch = AsyncMock(return_value=response)

    with patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)):
        result = await update_hubspot_ticket_route(
            "ticket-1",
            "closed",
            pipeline_id="ai-triage",
            owner_id=owner_id,
        )

    assert result["updated"] is True
    assert result["owner_id"] == owner_id
    response.raise_for_status.assert_called_once()
    assert client.patch.await_args.kwargs["json"] == {
        "properties": {
            "hs_pipeline_stage": "closed",
            "hs_pipeline": "ai-triage",
            "hubspot_owner_id": owner_id,
        }
    }


@pytest.mark.asyncio
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
    HUBSPOT_N1_NEW_STAGE_ID="ai-stage",
)
async def test_guarded_route_never_patches_after_concurrent_human_ownership() -> None:
    fresh_context = {
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "human-owner",
        "errors": [],
        "conversation_history": [
            {
                "id": "turn-1",
                "direction": "INCOMING",
                "text": "Aguardando",
            }
        ],
    }

    hydrate = AsyncMock(return_value=fresh_context)
    with (
        patch.object(hubspot, "hydrate_thread_context", new=hydrate),
        patch.object(hubspot.httpx, "AsyncClient") as client_factory,
    ):
        result = await update_hubspot_ticket_route(
            "ticket-1",
            "closed",
            pipeline_id="ai-pipeline",
            eligibility_thread_id="thread-1",
            expected_customer_turn_id="turn-1",
        )

    assert result["updated"] is False
    assert result["suppressed"] is True
    assert result["reason"] == "ticket_owned_by_human"
    hydrate.assert_awaited_once_with(
        "thread-1",
        ticket_id="ticket-1",
        timeout_seconds=20.0,
    )
    client_factory.assert_not_called()


def test_build_salomao_prompt_uses_latest_incoming_message() -> None:
    context = {
        "ticket_id": "123",
        "subject": "Ajuda no evento",
        "conversation_history": [
            {"direction": "INCOMING", "text": "Oi", "created_at": "2026-01-01T10:00:00Z"},
            {"direction": "OUTGOING", "text": "Como posso ajudar?", "created_at": "2026-01-01T10:01:00Z"},
            {
                "direction": "INCOMING",
                "text": "Meu evento nao aparece no app.",
                "created_at": "2026-01-01T10:02:00Z",
            },
        ],
    }

    prompt = build_salomao_prompt_from_hubspot_context(context)

    assert prompt is not None
    assert "Ticket: 123" in prompt
    assert "Assunto: Ajuda no evento" in prompt
    assert "Turno atual do cliente (mensagens consecutivas, em ordem):\nMeu evento nao aparece no app." in prompt


def test_build_salomao_prompt_groups_consecutive_customer_messages() -> None:
    context = {
        "ticket_id": "123",
        "subject": "Planos",
        "conversation_history": [
            {"direction": "OUTGOING", "text": "Como posso ajudar?", "id": "m1"},
            {"direction": "INCOMING", "text": "Tenho interesse", "id": "m2"},
            {"direction": "INCOMING", "text": "nos planos e valores", "id": "m3"},
            {"direction": "INCOMING", "text": "para minha igreja", "id": "m4"},
        ],
    }

    prompt = build_salomao_prompt_from_hubspot_context(context)

    assert prompt is not None
    assert "1. Tenho interesse" in prompt
    assert "2. nos planos e valores" in prompt
    assert "3. para minha igreja" in prompt
    assert prompt.index("1. Tenho interesse") < prompt.index("3. para minha igreja")


def test_build_salomao_prompt_marks_reopened_context_for_retriage() -> None:
    context = {
        "ticket_id": "123",
        "subject": "Evento",
        "lifecycle_context": {
            "is_reopened": True,
            "attendance_sequence": 2,
            "reopened_from_state": "CLOSED",
        },
        "conversation_history": [
            {"direction": "OUTGOING", "text": "O caso anterior foi concluido.", "id": "m1"},
            {"direction": "INCOMING", "text": "Voltei com outro problema.", "id": "m2"},
        ],
    }

    prompt = build_salomao_prompt_from_hubspot_context(context)

    assert prompt is not None
    assert "CONVERSA REABERTA" in prompt
    assert "Ciclo de atendimento: 2" in prompt
    assert "Estado anterior: CLOSED" in prompt
    assert "retomou o assunto anterior" in prompt


def test_build_salomao_prompt_skips_when_no_incoming_message() -> None:
    context = {
        "ticket_id": "123",
        "conversation_history": [
            {"direction": "OUTGOING", "text": "Resposta do suporte"},
        ],
    }

    assert build_salomao_prompt_from_hubspot_context(context) is None


def test_build_salomao_prompt_skips_stale_incoming_after_outgoing_reply() -> None:
    context = {
        "ticket_id": "123",
        "conversation_history": [
            {"direction": "INCOMING", "text": "Preciso de ajuda"},
            {"direction": "OUTGOING", "text": "Resposta já enviada"},
        ],
    }

    assert build_salomao_prompt_from_hubspot_context(context) is None


def test_build_salomao_prompt_accepts_image_without_caption() -> None:
    context = {
        "ticket_id": "123",
        "conversation_history": [
            {
                "direction": "INCOMING",
                "text": "",
                "attachments": [
                    {"type": "FILE", "fileUsageType": "IMAGE", "url": "https://cdn.hubspotusercontent.com/a.png"}
                ],
            },
        ],
    }

    prompt = build_salomao_prompt_from_hubspot_context(context)

    assert prompt is not None
    assert "Turno atual do cliente (mensagens consecutivas, em ordem):\n[Imagem enviada pelo cliente]" in prompt


async def test_fetch_history_keeps_hubspot_attachments() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "m1",
                        "direction": "INCOMING",
                        "text": "",
                        "attachments": [{"type": "FILE", "fileUsageType": "IMAGE", "fileId": "42"}],
                        "client": {"clientType": "INTEGRATION", "integrationAppId": 19550369},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        history = await _fetch_conversation_history(client, "thread-1")

    assert history[0]["attachments"][0]["fileId"] == "42"
    assert history[0]["client_type"] == "INTEGRATION"
    assert history[0]["integration_app_id"] == "19550369"


async def test_download_image_attachment_detects_image_and_encodes_base64(monkeypatch) -> None:
    monkeypatch.setattr(hubspot, "_validate_public_attachment_url", AsyncMock())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") in {None, ""}
        return httpx.Response(200, content=PNG_BYTES, headers={"Content-Type": "application/octet-stream"})

    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer secret"},
        transport=httpx.MockTransport(handler),
    ) as client:
        encoded, mime_type = await _download_image_attachment(
            client,
            {"type": "FILE", "url": "https://cdn.hubspotusercontent.com/image.png"},
        )

    assert base64.b64decode(encoded) == PNG_BYTES
    assert mime_type == "image/png"


async def test_download_image_attachment_resolves_private_file_id(monkeypatch) -> None:
    monkeypatch.setattr(hubspot, "_validate_public_attachment_url", AsyncMock())

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/files/v3/files/42/signed-url":
            return httpx.Response(200, json={"url": "https://cdn.hubspotusercontent.com/private.png"})
        return httpx.Response(200, content=PNG_BYTES)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        encoded, mime_type = await _download_image_attachment(client, {"type": "FILE", "fileId": "42"})

    assert base64.b64decode(encoded) == PNG_BYTES
    assert mime_type == "image/png"


async def test_download_image_attachment_requires_url_or_file_id() -> None:
    with pytest.raises(ValueError, match="missing"):
        await _download_image_attachment(MagicMock(), {})


async def test_download_image_attachment_rejects_oversized_content(monkeypatch) -> None:
    monkeypatch.setattr(hubspot, "_validate_public_attachment_url", AsyncMock())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PNG_BYTES, headers={"Content-Length": "100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="size limit"):
            await _download_image_attachment(
                client,
                {"type": "FILE", "url": "https://cdn.hubspotusercontent.com/image.png"},
                max_bytes=12,
            )


async def test_download_image_attachment_rejects_non_image_content(monkeypatch) -> None:
    monkeypatch.setattr(hubspot, "_validate_public_attachment_url", AsyncMock())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not an image")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="supported image"):
            await _download_image_attachment(
                client,
                {"type": "FILE", "url": "https://cdn.hubspotusercontent.com/image.png"},
            )


def test_build_conversation_context_from_hubspot_context() -> None:
    context = {
        "ticket_id": "123",
        "pipeline": "support",
        "pipeline_stage": "open",
        "owner_id": "owner-1",
        "church_id": "35120",
        "thread_ids": ["thread-1"],
        "contact_ids": ["contact-1"],
        "lifecycle_context": {
            "service_cycle_id": "cycle-2",
            "service_cycle_idempotency_key": "cycle-key-2",
            "attendance_sequence": 2,
            "is_reopened": True,
            "reopen_count": 1,
            "reopened_from_state": "CLOSED",
            "reopen_reason": "Customer returned after closure.",
        },
        "conversation_history": [
            {"direction": "OUTGOING", "text": "Como posso ajudar?", "sender": "agent-1", "id": "m1"},
            {"direction": "INCOMING", "text": "Meu evento nao aparece.", "sender": "visitor-1", "id": "m2"},
        ],
    }

    conversation_context = build_conversation_context_from_hubspot_context(
        context,
        session_id="hubspot-ticket-123",
        is_off_hours=True,
    )

    assert conversation_context.channel == "hubspot"
    assert conversation_context.session_id == "hubspot-ticket-123"
    assert conversation_context.ticket_id == "123"
    assert conversation_context.thread_id == "thread-1"
    assert conversation_context.contact_id == "contact-1"
    assert conversation_context.church_id == "35120"
    assert conversation_context.is_off_hours is True
    assert conversation_context.service_cycle_id == "cycle-2"
    assert conversation_context.service_cycle_idempotency_key == "cycle-key-2"
    assert conversation_context.attendance_sequence == 2
    assert conversation_context.is_reopened is True
    assert conversation_context.reopen_count == 1
    assert conversation_context.reopened_from_state == "CLOSED"
    assert conversation_context.recent_messages[-1].direction == "INCOMING"
    assert "send_thread_reply" in conversation_context.allowed_actions
    assert conversation_context.missing_context == []


def test_build_conversation_context_keeps_image_only_message() -> None:
    context = {
        "ticket_id": "123",
        "thread_ids": ["thread-1"],
        "conversation_history": [
            {
                "direction": "INCOMING",
                "text": "",
                "attachments": [{"type": "FILE", "fileUsageType": "IMAGE", "fileId": "42"}],
            }
        ],
    }

    conversation_context = build_conversation_context_from_hubspot_context(
        context,
        session_id="hubspot-ticket-123",
    )

    assert conversation_context.recent_messages[-1].text == "[Imagem enviada pelo cliente]"
    assert "recent_messages" not in conversation_context.missing_context


def test_build_conversation_context_always_allows_reply_action_for_whatsapp(settings) -> None:
    settings.HUBSPOT_AI_REPLY_DISABLED_CHANNELS = "whatsapp"
    context = {
        "ticket_id": "123",
        "originating_channel": "whatsapp",
        "thread_ids": ["thread-1"],
        "conversation_history": [
            {"direction": "INCOMING", "text": "Oi", "sender": "visitor-1", "id": "m1"},
        ],
    }

    conversation_context = build_conversation_context_from_hubspot_context(
        context,
        session_id="hubspot-ticket-123",
    )

    assert conversation_context.can_send_reply is True
    assert "send_thread_reply" in conversation_context.allowed_actions


def test_auth_headers_and_image_helpers(monkeypatch) -> None:
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="não configurado"):
        _auth_headers()

    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    assert _auth_headers()["Authorization"] == "Bearer test-token"
    assert _image_mime_type(b"\xff\xd8\xffrest") == "image/jpeg"
    assert _image_mime_type(b"GIF89arest") == "image/gif"
    assert _image_mime_type(b"RIFFxxxxWEBPrest") == "image/webp"
    assert _image_mime_type(b"text") is None
    assert _is_allowed_attachment_url("https://api.hubapi.com/file")
    assert _is_allowed_attachment_url("https://cdn.hubspotusercontent-eu1.net/file")
    assert not _is_allowed_attachment_url("http://api.hubapi.com/file")
    assert not _is_allowed_attachment_url("https://example.com/file")
    assert not _is_allowed_attachment_url("https://hubspotusercontent.attacker.example/file")
    assert not _is_allowed_attachment_url("https://cdn.hubspotusercontent-evil.net/file")
    assert not _is_allowed_attachment_url("https://api.hubapi.com.attacker.example/file")


@pytest.mark.asyncio
async def test_attachment_dns_must_resolve_only_to_public_addresses(monkeypatch) -> None:
    def public_dns(*_args, **_kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(hubspot.socket, "getaddrinfo", public_dns)
    await hubspot._validate_public_attachment_url("https://cdn.hubspotusercontent.com/image.png")

    def private_dns(*_args, **_kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(hubspot.socket, "getaddrinfo", private_dns)
    with pytest.raises(ValueError, match="non-public"):
        await hubspot._validate_public_attachment_url("https://cdn.hubspotusercontent.com/image.png")


@pytest.mark.asyncio
async def test_attachment_redirect_target_is_revalidated(monkeypatch) -> None:
    def public_dns(*_args, **_kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(hubspot.socket, "getaddrinfo", public_dns)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://attacker.example/private.png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="not trusted"):
            await _download_image_attachment(
                client,
                {"url": "https://cdn.hubspotusercontent.com/image.png"},
            )


@pytest.mark.asyncio
async def test_attachment_dns_resolution_failures_are_rejected(monkeypatch) -> None:
    def failed_dns(*_args, **_kwargs):
        raise OSError("dns unavailable")

    monkeypatch.setattr(hubspot.socket, "getaddrinfo", failed_dns)
    with pytest.raises(ValueError, match="could not be resolved"):
        await hubspot._validate_public_attachment_url("https://cdn.hubspotusercontent.com/image.png")

    monkeypatch.setattr(hubspot.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    with pytest.raises(ValueError, match="did not resolve"):
        await hubspot._validate_public_attachment_url("https://cdn.hubspotusercontent.com/image.png")


@pytest.mark.asyncio
async def test_attachment_allows_revalidated_redirect_between_trusted_hosts(monkeypatch) -> None:
    monkeypatch.setattr(hubspot, "_validate_public_attachment_url", AsyncMock())
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(
                302,
                headers={"Location": "https://cdn.hubspotusercontent-eu1.net/final.png"},
            )
        return httpx.Response(200, content=PNG_BYTES)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        encoded, mime_type = await _download_image_attachment(
            client,
            {"url": "https://cdn.hubspotusercontent.com/image.png"},
        )

    assert len(requests) == 2
    assert base64.b64decode(encoded) == PNG_BYTES
    assert mime_type == "image/png"


@pytest.mark.asyncio
async def test_attachment_redirect_without_location_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(hubspot, "_validate_public_attachment_url", AsyncMock())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="redirect limit"):
            await _download_image_attachment(
                client,
                {"url": "https://cdn.hubspotusercontent.com/image.png"},
            )


def test_attachment_and_recipient_helpers() -> None:
    context = {
        "conversation_history": [
            {"direction": "OUTGOING", "text": "ignore"},
            {
                "direction": "INCOMING",
                "attachments": [{"type": "FILE", "name": "photo.JPG"}],
            },
        ]
    }
    assert _latest_incoming_image_attachment(context) == {"type": "FILE", "name": "photo.JPG"}
    assert _recipient_from_sender(
        {
            "actorId": "visitor",
            "name": "Maria",
            "recipientField": "to",
            "deliveryIdentifier": {"type": "PHONE_NUMBER", "value": "123"},
        }
    ) == {
        "actorId": "visitor",
        "name": "Maria",
        "recipientField": "to",
        "deliveryIdentifiers": [{"type": "PHONE_NUMBER", "value": "123"}],
    }

    assert hubspot._parse_restored_thread_ids(["12", "", 34]) == ["12", "34"]
    assert hubspot._parse_restored_thread_ids(None) == []
    assert hubspot._parse_restored_thread_ids('["56", "78"]') == ["56", "78"]
    assert hubspot._parse_restored_thread_ids("threads: 90 and 12") == ["90", "12"]


@pytest.mark.asyncio
async def test_resolve_attachment_url_variants() -> None:
    client = MagicMock()
    assert await _resolve_attachment_url(client, {"url": "https://example.test/file"}) == "https://example.test/file"
    assert await _resolve_attachment_url(client, {}) is None

    response = MagicMock()
    response.json.return_value = {"url": "https://cdn.hubspotusercontent.com/private.png"}
    client.get = AsyncMock(return_value=response)
    assert await _resolve_attachment_url(client, {"fileId": "42"}) == ("https://cdn.hubspotusercontent.com/private.png")
    response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_download_rejects_untrusted_and_streamed_oversized_content(monkeypatch) -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="not trusted"):
        await _download_image_attachment(client, {"url": "https://example.com/image.png"})

    monkeypatch.setattr(hubspot, "_validate_public_attachment_url", AsyncMock())

    class StreamResponse:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.is_redirect = False

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield PNG_BYTES

    stream_context = MagicMock()
    stream_context.__aenter__ = AsyncMock(return_value=StreamResponse())
    stream_context.__aexit__ = AsyncMock(return_value=False)
    client.stream.return_value = stream_context
    with pytest.raises(ValueError, match="size limit"):
        await _download_image_attachment(
            client,
            {"url": "https://cdn.hubspotusercontent.com/image.png"},
            max_bytes=10,
        )


@pytest.mark.asyncio
async def test_hydrate_ticket_context_success(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    ticket = {
        "properties": {
            "subject": "Ajuda",
            "content": "Conteúdo",
            "hubspot_owner_id": "owner",
            "source_type": "CHAT",
            "hs_pipeline": "support",
            "hs_pipeline_stage": "new",
            "hs_ticket_priority": "HIGH",
            "codigo_de_igreja_local___ticket": "T35120",
        },
        "associations": {
            "contacts": {"results": [{"id": "contact-1"}, {}]},
            "conversations": {"results": [{"id": "thread-2"}, {"id": "thread-1"}]},
        },
    }
    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_ticket", new=AsyncMock(return_value=ticket)),
        patch.object(hubspot, "_fetch_thread", new=AsyncMock(side_effect=[{"id": "thread-2"}, {"id": "thread-1"}])),
        patch.object(
            hubspot,
            "_fetch_conversation_history",
            new=AsyncMock(
                side_effect=[
                    [{"id": "late", "direction": "INCOMING", "text": "B", "created_at": "2026-02-02"}],
                    [{"id": "early", "direction": "INCOMING", "text": "A", "created_at": "2026-01-01"}],
                ]
            ),
        ),
        patch.object(hubspot, "_hydrate_latest_incoming_image", new=AsyncMock()) as hydrate_image,
    ):
        context = await hydrate_ticket_context("ticket-1")

    assert context["subject"] == "Ajuda"
    assert context["church_id"] == "T35120"
    assert context["contact_ids"] == ["contact-1"]
    assert context["thread_ids"] == ["thread-2"]
    assert [message["id"] for message in context["conversation_history"]] == ["late"]
    assert context["errors"] == []
    hydrate_image.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["status", "network"])
async def test_hydrate_ticket_context_returns_partial_error(monkeypatch, error_kind: str) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    request = httpx.Request("GET", "https://api.hubapi.com/ticket")
    if error_kind == "status":
        response = httpx.Response(404, request=request)
        error: httpx.HTTPError = httpx.HTTPStatusError("missing", request=request, response=response)
    else:
        error = httpx.ConnectError("offline", request=request)

    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_ticket", new=AsyncMock(side_effect=error)),
    ):
        context = await hydrate_ticket_context("ticket-1")

    assert context["ticket_id"] == "ticket-1"
    assert context["errors"] == (["ticket_fetch:404"] if error_kind == "status" else ["ticket_fetch:ConnectError"])


@pytest.mark.asyncio
async def test_hydrate_ticket_context_keeps_partial_thread_failure(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    request = httpx.Request("GET", "https://api.hubapi.com/thread")
    ticket = {
        "properties": {},
        "associations": {"conversations": {"results": [{"id": "bad-thread"}]}},
    }
    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_ticket", new=AsyncMock(return_value=ticket)),
        patch.object(
            hubspot, "_fetch_thread", new=AsyncMock(side_effect=httpx.ConnectError("offline", request=request))
        ),
        patch.object(hubspot, "_hydrate_latest_incoming_image", new=AsyncMock()),
    ):
        context = await hydrate_ticket_context("ticket-1")

    assert context["errors"] == ["history:bad-thread"]
    assert context["thread_ids"] == []
    assert context["conversation_history"] == []


@pytest.mark.asyncio
async def test_hydrate_ticket_context_skips_stale_thread_and_uses_active_one(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    request = httpx.Request("GET", "https://api.hubapi.com/thread/stale")
    response = httpx.Response(404, request=request)
    stale = httpx.HTTPStatusError("missing", request=request, response=response)
    ticket = {
        "properties": {},
        "associations": {"conversations": {"results": [{"id": "stale-thread"}, {"id": "active-thread"}]}},
    }
    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_ticket", new=AsyncMock(return_value=ticket)),
        patch.object(
            hubspot,
            "_fetch_thread",
            new=AsyncMock(side_effect=[stale, {"id": "active-thread"}]),
        ),
        patch.object(
            hubspot,
            "_fetch_conversation_history",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "incoming-1",
                        "thread_id": "active-thread",
                        "direction": "INCOMING",
                        "text": "Como criar um cupom?",
                        "created_at": "2026-07-17T14:49:00Z",
                    }
                ]
            ),
        ),
        patch.object(hubspot, "_hydrate_latest_incoming_image", new=AsyncMock()),
    ):
        context = await hydrate_ticket_context("ticket-1")

    assert context["thread_ids"] == ["active-thread"]
    assert context["conversation_history"][0]["thread_id"] == "active-thread"
    assert context["errors"] == []


@pytest.mark.asyncio
async def test_hydrate_thread_context_success_and_mock(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    thread = {
        "threadAssociations": {"associatedTicketId": "ticket-1"},
        "associatedContactId": "contact-1",
        "originalChannelId": "CHAT",
    }
    ticket = {
        "properties": {
            "subject": "Caso N2",
            "hs_pipeline": "634240100",
            "hs_pipeline_stage": "1060950862",
            "codigo_de_igreja_local___ticket": "35120",
        },
        "associations": {},
    }
    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_thread", new=AsyncMock(return_value=thread)),
        patch.object(hubspot, "_fetch_ticket", new=AsyncMock(return_value=ticket)),
        patch.object(
            hubspot,
            "_fetch_conversation_history",
            new=AsyncMock(return_value=[{"id": "m1", "direction": "INCOMING", "text": "Oi"}]),
        ),
        patch.object(hubspot, "_hydrate_latest_incoming_image", new=AsyncMock()),
    ):
        context = await hydrate_thread_context("thread-1", limit=5)

    assert context["ticket_id"] == "ticket-1"
    assert context["contact_ids"] == ["contact-1"]
    assert context["originating_channel"] == "CHAT"
    assert context["church_id"] == "35120"
    assert context["pipeline"] == "634240100"
    assert context["pipeline_stage"] == "1060950862"

    with patch.object(hubspot, "USE_MOCK_HUBSPOT", True):
        mocked = await hydrate_thread_context("thread-mock")
    assert mocked["thread_ids"] == ["thread-mock"]
    assert mocked["conversation_history"][0]["thread_id"] == "thread-mock"


@pytest.mark.asyncio
async def test_fetch_thread_requests_ticket_association(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    response = MagicMock()
    response.json.return_value = {"id": "thread-1"}
    client = MagicMock()
    client.get = AsyncMock(return_value=response)

    result = await hubspot._fetch_thread(client, "thread-1")

    assert result == {"id": "thread-1"}
    client.get.assert_awaited_once_with(
        "https://api.hubapi.com/conversations/v3/conversations/threads/thread-1",
        params={"association": "TICKET"},
    )
    response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_hydrate_thread_context_uses_caller_ticket_when_thread_association_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    thread = {
        "threadAssociations": {},
        "associatedContactId": "contact-1",
        "originalChannelId": "WHATSAPP",
    }
    ticket = {
        "properties": {
            "subject": "Ticket conhecido",
            "hs_pipeline": "ai-pipeline",
            "hs_pipeline_stage": "ai-active",
        },
        "associations": {},
    }
    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_thread", new=AsyncMock(return_value=thread)),
        patch.object(hubspot, "_fetch_ticket", new=AsyncMock(return_value=ticket)) as fetch_ticket,
        patch.object(
            hubspot,
            "_fetch_conversation_history",
            new=AsyncMock(return_value=[{"id": "m1", "direction": "INCOMING", "text": "Oi"}]),
        ),
        patch.object(hubspot, "_hydrate_latest_incoming_image", new=AsyncMock()),
    ):
        context = await hydrate_thread_context(
            "thread-without-ticket-association",
            ticket_id="ticket-from-worker",
        )

    fetch_ticket.assert_awaited_once_with(client, "ticket-from-worker")
    assert context["ticket_id"] == "ticket-from-worker"
    assert context["ticket_id_source"] == "caller"
    assert context["pipeline"] == "ai-pipeline"
    assert context["pipeline_stage"] == "ai-active"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_hydrate_thread_context_recovers_ticket_from_canonical_instance(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:thread-reentered",
        hubspot_thread_id="thread-reentered",
        hubspot_ticket_id="ticket-persisted",
    )
    thread = {
        "threadAssociations": {},
        "associatedContactId": "contact-1",
        "originalChannelId": "WHATSAPP",
    }
    ticket = {
        "properties": {
            "subject": "Ticket reaberto",
            "hs_pipeline": "ai-pipeline",
            "hs_pipeline_stage": "ai-active",
        },
        "associations": {},
    }
    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_thread", new=AsyncMock(return_value=thread)),
        patch.object(hubspot, "_fetch_ticket", new=AsyncMock(return_value=ticket)) as fetch_ticket,
        patch.object(
            hubspot,
            "_fetch_conversation_history",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "customer-after-reopen",
                        "direction": "INCOMING",
                        "text": "Quero falar com um atendente",
                        "created_at": "2026-07-28T23:56:25Z",
                    }
                ]
            ),
        ),
        patch.object(hubspot, "_hydrate_latest_incoming_image", new=AsyncMock()),
    ):
        context = await hydrate_thread_context("thread-reentered")

    fetch_ticket.assert_awaited_once_with(client, "ticket-persisted")
    assert context["ticket_id"] == "ticket-persisted"
    assert context["ticket_id_source"] == "local_canonical_instance"
    assert context["pipeline"] == "ai-pipeline"
    assert context["pipeline_stage"] == "ai-active"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["status", "network"])
async def test_hydrate_thread_context_errors(monkeypatch, error_kind: str) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    request = httpx.Request("GET", "https://api.hubapi.com/thread")
    if error_kind == "status":
        response = httpx.Response(403, request=request)
        error: httpx.HTTPError = httpx.HTTPStatusError("forbidden", request=request, response=response)
    else:
        error = httpx.ConnectError("offline", request=request)
    client = MagicMock()
    with (
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
        patch.object(hubspot, "_fetch_thread", new=AsyncMock(side_effect=error)),
    ):
        context = await hydrate_thread_context("thread-1")
    assert context["errors"] == (["thread_fetch:403"] if error_kind == "status" else ["thread_fetch:ConnectError"])


@pytest.mark.asyncio
async def test_send_reply_preconditions_and_success(monkeypatch) -> None:
    assert await send_salomao_reply_to_hubspot_thread({}, "Olá") == {
        "sent": False,
        "reason": "no_incoming_message",
    }
    incomplete = {"conversation_history": [{"direction": "INCOMING", "text": "Oi"}]}
    missing = await send_salomao_reply_to_hubspot_thread(incomplete, "Olá")
    assert missing["reason"] == "missing_fields"

    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("HUBSPOT_SALOMAO_SENDER_ACTOR_ID", "agent")
    context = {
        "conversation_history": [
            {
                "id": "m1",
                "thread_id": "thread-1",
                "channel_id": "channel",
                "channel_account_id": "account",
                "direction": "INCOMING",
                "text": "Oi",
                "senders": [{"actorId": "visitor"}],
            }
        ]
    }
    response = MagicMock()
    response.json.return_value = {"id": "reply-1"}
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    reply = (
        "## Como fazer\n\n"
        "1. Acesse **Financeiro**.\n"
        "2. Localize a transação.\n\n"
        "## Atenção\n\n- O estorno depende do gateway."
    )
    with (
        patch.object(
            hubspot,
            "refresh_salomao_reply_context",
            new=AsyncMock(
                return_value={
                    "eligible": True,
                    "reason": "eligible",
                    "retryable": False,
                    "context": context,
                }
            ),
        ),
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
    ):
        result = await send_salomao_reply_to_hubspot_thread(context, reply)
    assert result["sent"] is True
    assert result["message_id"] == "reply-1"
    response.raise_for_status.assert_called_once()
    payload = client.post.await_args.kwargs["json"]
    assert payload["text"] == reply
    assert "<h4>Como fazer</h4>" in payload["richText"]
    assert "<ol><li>Acesse <strong>Financeiro</strong>.</li>" in payload["richText"]
    assert "<ul><li>O estorno depende do gateway.</li></ul>" in payload["richText"]
    assert "##" not in payload["richText"]


@pytest.mark.asyncio
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
    HUBSPOT_N1_NEW_STAGE_ID="ai-active",
    HUBSPOT_SALOMAO_SENDER_ACTOR_ID="A-salomao",
)
async def test_send_reply_rechecks_route_and_suppresses_late_response(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    context = {
        "ticket_id": "ticket-1",
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-active",
        "owner_id": "",
        "conversation_history": [
            {
                "id": "customer-turn",
                "thread_id": "thread-1",
                "channel_id": "channel",
                "channel_account_id": "account",
                "direction": "INCOMING",
                "text": "Aguardando",
                "senders": [{"actorId": "visitor"}],
            }
        ],
    }
    fresh_context = {
        **context,
        "pipeline": "support-pipeline",
        "pipeline_stage": "human-active",
        "owner_id": "human-owner",
    }

    hydrate = AsyncMock(return_value=fresh_context)
    with (
        patch.object(hubspot, "hydrate_thread_context", new=hydrate),
        patch.object(hubspot.httpx, "AsyncClient") as client_factory,
    ):
        result = await send_salomao_reply_to_hubspot_thread(context, "Resposta tardia")

    assert result == {
        "sent": False,
        "suppressed": True,
        "retryable": False,
        "reason": "ticket_left_ai_pipeline",
    }
    hydrate.assert_awaited_once_with("thread-1", ticket_id="ticket-1")
    client_factory.assert_not_called()


@pytest.mark.asyncio
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="ai-pipeline",
    HUBSPOT_N1_NEW_STAGE_ID="ai-active",
    HUBSPOT_SALOMAO_SENDER_ACTOR_ID="A-salomao",
)
async def test_customer_turn_change_suppresses_stale_reply_without_retry(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    first_message = {
        "id": "customer-turn-1",
        "thread_id": "thread-1",
        "channel_id": "channel",
        "channel_account_id": "account",
        "direction": "INCOMING",
        "text": "Primeira mensagem",
        "senders": [{"actorId": "visitor"}],
    }
    context = {
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-active",
        "owner_id": "",
        "conversation_history": [first_message],
    }
    fresh_context = {
        **context,
        "errors": [],
        "conversation_history": [
            first_message,
            {
                **first_message,
                "id": "customer-turn-2",
                "text": "Complemento mais recente",
            },
        ],
    }

    with (
        patch.object(
            hubspot,
            "hydrate_thread_context",
            new=AsyncMock(return_value=fresh_context),
        ),
        patch.object(hubspot.httpx, "AsyncClient") as client_factory,
    ):
        result = await send_salomao_reply_to_hubspot_thread(context, "Resposta antiga")

    assert result == {
        "sent": False,
        "suppressed": True,
        "retryable": False,
        "reason": "customer_turn_changed",
        "current_customer_turn_id": "customer-turn-2",
        "current_thread_id": "thread-1",
    }
    client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_create_thread_comment_publishes_internal_observation(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    response = MagicMock()
    response.json.return_value = {"id": "comment-1"}
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    observation = (
        "## Resumo automático do Salomão para o N1\n\n"
        "**Tom percebido:** Irritado\n\n"
        "**Próximo passo recomendado:** Acolher e assumir o caso."
    )

    with patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)):
        result = await create_hubspot_thread_comment("thread-1", observation)

    assert result == {
        "created": True,
        "thread_id": "thread-1",
        "message_id": "comment-1",
    }
    response.raise_for_status.assert_called_once()
    payload = client.post.await_args.kwargs["json"]
    assert payload["type"] == "COMMENT"
    assert payload["text"] == observation
    assert "<h4>Resumo automático do Salomão para o N1</h4>" in payload["richText"]
    assert "recipients" not in payload
    assert "senderActorId" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["status", "network"])
async def test_create_thread_comment_handles_http_errors(monkeypatch, error_kind: str) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    request = httpx.Request("POST", "https://api.hubapi.com/messages")
    if error_kind == "status":
        response = httpx.Response(429, text="rate limit", request=request)
        error: httpx.HTTPError = httpx.HTTPStatusError("limited", request=request, response=response)
    else:
        error = httpx.ConnectError("offline", request=request)
    client = MagicMock()
    client.post = AsyncMock(side_effect=error)

    with patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)):
        result = await create_hubspot_thread_comment("thread-1", "Resumo")

    assert result["reason"] == ("http:429" if error_kind == "status" else "ConnectError")


def test_markdown_to_hubspot_rich_text_escapes_raw_html() -> None:
    rendered = hubspot.markdown_to_hubspot_rich_text("Texto <script>alert('x')</script> com `código` e *ênfase*.")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<code>código</code>" in rendered
    assert "<em>ênfase</em>" in rendered


def test_markdown_to_hubspot_rich_text_renders_safe_links() -> None:
    rendered = hubspot.markdown_to_hubspot_rich_text("[Formulário](https://form.typeform.com/to/S7EC8j4N)")

    assert (
        '<a href="https://form.typeform.com/to/S7EC8j4N" target="_blank" rel="noopener noreferrer">Formulário</a>'
    ) in rendered
    unsafe = hubspot.markdown_to_hubspot_rich_text("[Clique](javascript:alert(1))")
    assert "<a " not in unsafe


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["status", "network"])
async def test_send_reply_handles_http_errors(monkeypatch, error_kind: str) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("HUBSPOT_SALOMAO_SENDER_ACTOR_ID", "agent")
    context = {
        "conversation_history": [
            {
                "thread_id": "thread-1",
                "channel_id": "channel",
                "channel_account_id": "account",
                "direction": "INCOMING",
                "text": "Oi",
                "senders": [{"actorId": "visitor"}],
            }
        ]
    }
    request = httpx.Request("POST", "https://api.hubapi.com/messages")
    if error_kind == "status":
        response = httpx.Response(429, text="rate limit", request=request)
        error: httpx.HTTPError = httpx.HTTPStatusError("limited", request=request, response=response)
    else:
        error = httpx.ConnectError("offline", request=request)
    client = MagicMock()
    client.post = AsyncMock(side_effect=error)
    with (
        patch.object(
            hubspot,
            "refresh_salomao_reply_context",
            new=AsyncMock(
                return_value={
                    "eligible": True,
                    "reason": "eligible",
                    "retryable": False,
                    "context": context,
                }
            ),
        ),
        patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)),
    ):
        result = await send_salomao_reply_to_hubspot_thread(context, "Olá")
    assert result["reason"] == ("http:429" if error_kind == "status" else "ConnectError")
