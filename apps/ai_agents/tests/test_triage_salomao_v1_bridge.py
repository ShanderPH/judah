"""Tests for the legacy triage endpoint bridge to Salomao v1."""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings

from apps.ai_agents.schemas import TriageRequest
from apps.ai_agents.services import triage_message
from apps.integrations.salomao_v1 import SalomaoV1ChatResult, SalomaoV1TokenUsage


@override_settings(SALOMAO_V1_BASE_URL="http://salomao.local")
def test_triage_message_returns_salomao_v1_answer() -> None:
    async def fake_send_chat_to_salomao_v1(*, message: str, session_id: str, **kwargs):
        assert message == "Como fazer um cupom de desconto?"
        assert session_id.startswith("whatsapp-")
        return SalomaoV1ChatResult(
            success=True,
            response="Para criar um cupom, acesse Eventos e configure o desconto.",
            session_id=session_id,
            transfer_requested=False,
            tokens=SalomaoV1TokenUsage(total=42),
        )

    with patch("apps.integrations.salomao_v1.send_chat_to_salomao_v1", fake_send_chat_to_salomao_v1):
        response = triage_message(
            TriageRequest(
                message="Como fazer um cupom de desconto?",
                channel="whatsapp",
            )
        )

    assert response.intent == "salomao_v1_answer"
    assert response.requires_human is False
    assert response.suggested_queue == "ai"
    assert "cupom" in response.reasoning
