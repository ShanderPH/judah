"""Tests for HubSpot chat context used by the Salomao v1 adapter."""

from __future__ import annotations

from apps.ai_agents.services.hubspot import (
    build_conversation_context_from_hubspot_context,
    build_salomao_prompt_from_hubspot_context,
)


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
