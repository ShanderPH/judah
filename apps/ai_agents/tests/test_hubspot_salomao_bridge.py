"""Tests for HubSpot chat context used by the Salomao v1 adapter."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

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
    hydrate_thread_context,
    hydrate_ticket_context,
    send_salomao_reply_to_hubspot_thread,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"image-content"


def _async_client_context(client: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


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
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        history = await _fetch_conversation_history(client, "thread-1")

    assert history[0]["attachments"][0]["fileId"] == "42"


async def test_download_image_attachment_detects_image_and_encodes_base64() -> None:
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


async def test_download_image_attachment_resolves_private_file_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/files/v3/files/42/signed-url":
            return httpx.Response(200, json={"url": "https://cdn.hubspotusercontent.com/private.png"})
        return httpx.Response(200, content=PNG_BYTES)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        encoded, mime_type = await _download_image_attachment(client, {"type": "FILE", "fileId": "42"})

    assert base64.b64decode(encoded) == PNG_BYTES
    assert mime_type == "image/png"


async def test_download_image_attachment_rejects_oversized_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PNG_BYTES, headers={"Content-Length": "100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="size limit"):
            await _download_image_attachment(
                client,
                {"type": "FILE", "url": "https://cdn.hubspotusercontent.com/image.png"},
                max_bytes=12,
            )


async def test_download_image_attachment_rejects_non_image_content() -> None:
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
        "thread_ids": ["thread-1"],
        "contact_ids": ["contact-1"],
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
    assert conversation_context.is_off_hours is True
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
async def test_download_rejects_untrusted_and_streamed_oversized_content() -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="not trusted"):
        await _download_image_attachment(client, {"url": "https://example.com/image.png"})

    class StreamResponse:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

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
    with patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)):
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
    with patch.object(hubspot.httpx, "AsyncClient", return_value=_async_client_context(client)):
        result = await send_salomao_reply_to_hubspot_thread(context, "Olá")
    assert result["reason"] == ("http:429" if error_kind == "status" else "ConnectError")
