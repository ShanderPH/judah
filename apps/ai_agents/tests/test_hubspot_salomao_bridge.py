"""Tests for HubSpot chat context used by the Salomao v1 bridge."""

from __future__ import annotations

from apps.ai_agents.services.hubspot import build_salomao_prompt_from_hubspot_context


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
