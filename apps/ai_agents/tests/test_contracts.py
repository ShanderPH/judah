"""Tests for typed handoff contracts between AI agents."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.ai_agents.contracts import (
    ConversationContext,
    ConversationMessage,
    HubSpotAction,
    SalomaoChatDraft,
    TriageDecision,
)


def test_agent_contracts_validate_expected_payloads() -> None:
    triage = TriageDecision(
        rota="ATENDIMENTO_IA",
        prioridade="MEDIA",
        sentimento="neutro",
        tags=["cupom"],
    )
    context = ConversationContext(
        channel="hubspot",
        session_id="hubspot-thread-123",
        ticket_id="456",
        thread_id="123",
        recent_messages=[
            ConversationMessage(
                direction="INCOMING",
                text="Como fazer um cupom de desconto?",
                message_id="m1",
            )
        ],
    )
    action = HubSpotAction(
        action_type="send_thread_reply",
        payload={"thread_id": "123"},
        idempotency_key="hubspot-thread:123:salomao-chat",
    )
    draft = SalomaoChatDraft(
        response_text="Acesse Eventos e configure o cupom na aba de descontos.",
        confidence=0.86,
        resolved=True,
        requires_human_handoff=False,
        recommended_actions=[],
    )

    assert triage.rota == "ATENDIMENTO_IA"
    assert context.recent_messages[0].direction == "INCOMING"
    assert action.action_type == "send_thread_reply"
    assert draft.resolved is True


def test_contracts_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationContext(
            channel="hubspot",
            session_id="hubspot-thread-123",
            unexpected="field",
        )
