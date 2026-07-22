"""Tests for the deterministic commercial-contact policy."""

from unittest.mock import AsyncMock, Mock

import pytest

from apps.ai_agents.services.commercial_contact import (
    COMMERCIAL_CONTACT_MESSAGE,
    handle_commercial_contact_from_hubspot_context,
    has_commercial_contact_intent,
)


def _context(*messages: tuple[str, str]) -> dict:
    return {
        "conversation_history": [
            {"direction": direction, "text": text, "id": f"m{index}"}
            for index, (direction, text) in enumerate(messages, start=1)
        ]
    }


@pytest.mark.parametrize(
    "message",
    [
        "Quero falar com o Comercial",
        "Pode me passar o contato da equipe de vendas?",
        "Tenho interesse em conhecer os planos e valores",
        "Gostaria de contratar a plataforma inChurch",
        "Quanto custa a inChurch?",
        "Me passa para o comercial, por favor",
        "Quais planos estão disponíveis?",
    ],
)
def test_explicit_commercial_intent_returns_approved_message(message: str) -> None:
    context = _context(("INCOMING", message))

    assert has_commercial_contact_intent(context) is True
    assert handle_commercial_contact_from_hubspot_context(context) == COMMERCIAL_CONTACT_MESSAGE
    assert "https://form.typeform.com/to/S7EC8j4N" in COMMERCIAL_CONTACT_MESSAGE


def test_commercial_intent_understands_consecutive_customer_messages() -> None:
    context = _context(
        ("OUTGOING", "Como posso ajudar?"),
        ("INCOMING", "Tenho interesse"),
        ("INCOMING", "nos planos e valores da inChurch"),
    )

    assert has_commercial_contact_intent(context) is True


def test_affirmative_reply_uses_recent_commercial_context() -> None:
    context = _context(
        ("OUTGOING", "Você gostaria de falar com o nosso time comercial?"),
        ("INCOMING", "Sim"),
    )

    assert has_commercial_contact_intent(context) is True


@pytest.mark.parametrize(
    "message",
    [
        "Como configurar o plano de contas?",
        "Qual o valor do ingresso do meu evento?",
        "O relatório de vendas não abre",
        "Como cadastrar um serviço no painel?",
    ],
)
def test_product_support_questions_do_not_trigger_commercial_form(message: str) -> None:
    context = _context(("INCOMING", message))

    assert has_commercial_contact_intent(context) is False
    assert handle_commercial_contact_from_hubspot_context(context) is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_commercial_reply_bypasses_protocol_lookup_and_models(monkeypatch) -> None:
    from apps.ai_agents.api import webhooks

    protocol_lookup = AsyncMock()
    apply_result = AsyncMock()
    advance = AsyncMock()
    supervisor = Mock()
    monkeypatch.setattr(webhooks, "handle_protocol_lookup_from_hubspot_context", protocol_lookup)
    monkeypatch.setattr(webhooks, "apply_supervisor_result", apply_result)
    monkeypatch.setattr(webhooks, "_advance_lifecycle_for_hubspot_context", advance)
    monkeypatch.setattr(webhooks, "SalomaoSupervisorAgent", supervisor)
    context = {
        "ticket_id": "ticket-commercial",
        "originating_channel": "chat",
        "thread_ids": ["thread-commercial"],
        "contact_ids": ["contact-commercial"],
        "conversation_history": [
            {"direction": "INCOMING", "text": "Quero falar com o Comercial", "id": "message-1"}
        ],
    }

    await webhooks._run_supervisor_for_hubspot_context(
        context,
        session_id="hubspot-thread-thread-commercial",
        ticket_id="ticket-commercial",
        require_incoming=True,
    )

    protocol_lookup.assert_not_awaited()
    supervisor.assert_not_called()
    apply_result.assert_awaited_once()
    result = apply_result.await_args.kwargs["result"]
    assert result.message == COMMERCIAL_CONTACT_MESSAGE
    assert result.model_name == "commercial_contact"
    assert result.tokens_used == 0
