"""Tests for triage behavior when the Salomao v1 adapter is configured."""

from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings

from apps.ai_agents.schemas import TriageRequest
from apps.ai_agents.services import triage_message


class FakeHeimdallResult:
    content = "Heimdall classificou como suporte tecnico."


class FakeHeimdallAgent:
    def run(self, message: str, *, session_id: str) -> FakeHeimdallResult:
        assert message == "Triage this message: Como fazer um cupom de desconto?"
        assert session_id.startswith("triage-")
        return FakeHeimdallResult()


@override_settings(SALOMAO_V1_BASE_URL="http://salomao.local")
def test_triage_message_uses_heimdall_even_when_salomao_v1_is_configured() -> None:
    with (
        patch("apps.ai_agents.agents.heimdall.heimdall_agent", FakeHeimdallAgent()),
        patch("apps.integrations.salomao_v1.send_chat_to_salomao_v1") as send_chat_to_salomao_v1,
    ):
        response = triage_message(
            TriageRequest(
                message="Como fazer um cupom de desconto?",
                channel="whatsapp",
            )
        )

    send_chat_to_salomao_v1.assert_not_called()
    assert response.intent == "support"
    assert response.requires_human is True
    assert "Heimdall" in response.reasoning
