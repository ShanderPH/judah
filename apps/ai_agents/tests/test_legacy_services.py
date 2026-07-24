"""Tests for compatibility AI service functions and legacy API wrappers."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.ai_agents.models import AgentSession, AgentTrace
from apps.ai_agents.schemas import ChatRequest, TriageRequest
from apps.ai_agents.services import chat_with_agent, get_or_create_session, triage_message


@pytest.mark.django_db
def test_session_lookup_create_and_legacy_chat() -> None:
    existing = AgentSession.objects.create(
        session_id="existing",
        agent_type="salomao",
        channel="web",
    )
    assert get_or_create_session("existing", "salomao", "web", "", "", "") == existing
    created = get_or_create_session("missing", "salomao", "web", "user", "church", "contact")
    assert created.session_id == "missing"

    payload = ChatRequest(
        message="Olá",
        session_id=created.session_id,
        agent_type="salomao",
        channel="web",
    )
    agent = Mock()
    agent.run.return_value = SimpleNamespace(content="Resposta")
    with patch("apps.ai_agents.agents.salomao.salomao_agent", agent):
        response = chat_with_agent(payload)
    assert response.message == "Resposta"
    assert AgentTrace.objects.filter(session=created).count() == 2


@pytest.mark.django_db
def test_legacy_chat_propagates_agent_failure() -> None:
    payload = ChatRequest(message="Olá", agent_type="heimdall", channel="web")
    agent = Mock()
    agent.run.side_effect = RuntimeError("offline")
    with patch("apps.ai_agents.agents.heimdall.heimdall_agent", agent), pytest.raises(RuntimeError):
        chat_with_agent(payload)


def test_triage_success_failure_and_api_wrapper() -> None:
    payload = TriageRequest(message="Ajuda", channel="chat")
    agent = Mock()
    agent.run.return_value = SimpleNamespace(content="Análise")
    with patch("apps.ai_agents.agents.heimdall.heimdall_agent", agent):
        result = triage_message(payload)
    assert result.intent == "support"
    assert result.reasoning == "Análise"

    agent.run.side_effect = RuntimeError("offline")
    with patch("apps.ai_agents.agents.heimdall.heimdall_agent", agent):
        result = triage_message(payload)
    assert result.intent == "unknown"
