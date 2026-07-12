"""Tests for HubSpot chat context used by the Salomao v1 adapter."""

from __future__ import annotations

import base64

import httpx
import pytest

from apps.ai_agents.services.hubspot import (
    _download_image_attachment,
    _fetch_conversation_history,
    build_conversation_context_from_hubspot_context,
    build_salomao_prompt_from_hubspot_context,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"image-content"


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
    assert "Mensagem atual do cliente:\nMeu evento nao aparece no app." in prompt


def test_build_salomao_prompt_skips_when_no_incoming_message() -> None:
    context = {
        "ticket_id": "123",
        "conversation_history": [
            {"direction": "OUTGOING", "text": "Resposta do suporte"},
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
    assert "Mensagem atual do cliente:\n[Imagem enviada pelo cliente]" in prompt


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


def test_build_conversation_context_blocks_reply_action_for_whatsapp(settings) -> None:
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

    assert conversation_context.can_send_reply is False
    assert "send_thread_reply" not in conversation_context.allowed_actions
