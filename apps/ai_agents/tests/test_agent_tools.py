"""Tests for lightweight Agno tool adapters."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.ai_agents.agents.tools.hubspot_tools import GetTicketInfo
from apps.ai_agents.agents.tools.jira_tools import SearchJiraIssues
from apps.ai_agents.agents.tools.knowledge_tools import SearchKnowledgeBase


def test_hubspot_tools_return_provider_data_and_safe_errors() -> None:
    client = Mock()
    client.get_ticket.return_value = {"id": "1"}
    client.search_contact_by_email.return_value = {"email": "a@example.com"}
    with patch("apps.integrations.hubspot.client.get_hubspot_client", return_value=client):
        toolkit = GetTicketInfo()
        assert toolkit.get_ticket("1") == {"id": "1"}
        assert toolkit.search_contact("a@example.com") == {"email": "a@example.com"}

    with patch("apps.integrations.hubspot.client.get_hubspot_client", side_effect=RuntimeError("offline")):
        assert GetTicketInfo().get_ticket("1") == {"error": "offline"}
        assert GetTicketInfo().search_contact("a@example.com") == {"error": "offline"}


def test_jira_tools_return_provider_data_and_safe_errors() -> None:
    client = Mock()
    client.search_issues.return_value = [{"key": "INCH-1"}]
    client.create_issue.return_value = {"key": "INCH-2"}
    with patch("apps.integrations.jira.client.get_jira_client", return_value=client):
        toolkit = SearchJiraIssues()
        assert toolkit.search_issues("login", 3) == [{"key": "INCH-1"}]
        assert toolkit.create_issue("Resumo", "Descrição", project_key="OPS") == {"key": "INCH-2"}

    with patch("apps.integrations.jira.client.get_jira_client", side_effect=RuntimeError("offline")):
        assert SearchJiraIssues().search_issues("login") == []
        assert SearchJiraIssues().create_issue("Resumo", "Descrição") == {"error": "offline"}


def test_knowledge_tool_normalizes_results_and_errors() -> None:
    results = [
        SimpleNamespace(article_id="a1", title="Artigo", summary="Resumo", score=0.95),
    ]
    with patch("apps.knowledge.services.semantic_search", return_value=results):
        assert SearchKnowledgeBase().search("consulta", top_k=1) == [
            {
                "article_id": "a1",
                "title": "Artigo",
                "summary": "Resumo",
                "score": 0.95,
            }
        ]

    with patch("apps.knowledge.services.semantic_search", side_effect=RuntimeError("offline")):
        assert SearchKnowledgeBase().search("consulta") == []
