import pytest
from pydantic import ValidationError

from apps.ai_agents.contracts import ConversationContext, ConversationMessage, SalomaoChatDraft


def test_independent_ai_contracts_validate_expected_payloads() -> None:
    context = ConversationContext(
        channel="api",
        session_id="session-1",
        recent_messages=[ConversationMessage(direction="INCOMING", text="Ajuda")],
    )
    draft = SalomaoChatDraft(
        response_text="Resposta",
        confidence=0.9,
        resolved=True,
        requires_human_handoff=False,
    )

    assert context.recent_messages[0].text == "Ajuda"
    assert draft.resolved is True


def test_contracts_reject_unknown_identification_payload() -> None:
    with pytest.raises(ValidationError):
        ConversationContext(channel="api", session_id="session-1", customer_identity={})
