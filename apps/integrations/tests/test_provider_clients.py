"""Unit tests for provider clients without external network access."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from apps.integrations.jira import client as jira_module
from apps.integrations.jira.client import JiraClient
from apps.integrations.pinecone_client import client as pinecone_module
from apps.integrations.pinecone_client.client import PineconeClient
from apps.integrations.supabase_client import client as supabase_module
from common.exceptions import ExternalServiceError


def test_jira_client_search_and_create() -> None:
    jira_sdk = Mock(server_url="https://jira.example")
    jira_sdk.search_issues.return_value = [
        SimpleNamespace(
            key="INCH-1",
            fields=SimpleNamespace(
                summary="Falha",
                status=SimpleNamespace(name="Open"),
                priority=SimpleNamespace(name="High"),
            ),
        ),
        SimpleNamespace(
            key="INCH-2",
            fields=SimpleNamespace(
                summary="Sem prioridade",
                status=SimpleNamespace(name="Backlog"),
                priority=None,
            ),
        ),
    ]
    jira_sdk.create_issue.return_value = SimpleNamespace(key="INCH-3")

    with (
        patch("apps.integrations.jira.client.JIRA", return_value=jira_sdk),
        patch("apps.integrations.jira.client._circuit_breaker.call", side_effect=lambda fn, *a, **kw: fn(*a, **kw)),
    ):
        client = JiraClient("https://jira.example", "user@example.com", "token")
        results = client.search_issues("login", max_results=2)
        created = client.create_issue("Resumo", "Descrição")

    assert results[0]["priority"] == "High"
    assert results[1]["priority"] == "None"
    assert created == {"key": "INCH-3", "url": "https://jira.example/browse/INCH-3"}
    jira_sdk.search_issues.assert_called_once_with('text ~ "login" ORDER BY created DESC', maxResults=2)


def test_jira_client_wraps_provider_errors() -> None:
    with (
        patch("apps.integrations.jira.client.JIRA"),
        patch("apps.integrations.jira.client._circuit_breaker.call", side_effect=RuntimeError("offline")),
    ):
        client = JiraClient("https://jira.example", "user@example.com", "token")
        with pytest.raises(ExternalServiceError):
            client.search_issues("login")
        with pytest.raises(ExternalServiceError):
            client.create_issue("Resumo", "Descrição")


@override_settings(JIRA_SERVER_URL="", JIRA_USER_EMAIL="", JIRA_API_TOKEN="")
def test_jira_singleton_requires_configuration() -> None:
    jira_module._jira_client = None
    with pytest.raises(ValueError):
        jira_module.get_jira_client()


@override_settings(
    JIRA_SERVER_URL="https://jira.example",
    JIRA_USER_EMAIL="user@example.com",
    JIRA_API_TOKEN="token",
)
def test_jira_singleton_reuses_client() -> None:
    jira_module._jira_client = None
    sentinel = Mock(spec=JiraClient)
    with patch("apps.integrations.jira.client.JiraClient", return_value=sentinel) as factory:
        assert jira_module.get_jira_client() is sentinel
        assert jira_module.get_jira_client() is sentinel
    factory.assert_called_once()


def test_pinecone_client_operations() -> None:
    index = Mock()
    index.upsert.return_value = {"upserted_count": 1}
    index.query.return_value = {
        "matches": [
            {"id": "v1", "score": 0.9, "metadata": {"article_id": "1"}},
            {"id": "v2", "score": 0.8},
        ]
    }
    embedding = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
    openai_client = Mock()
    openai_client.embeddings.create.return_value = embedding
    client = PineconeClient(index)

    with patch("openai.OpenAI", return_value=openai_client):
        assert client.upsert([{"id": "v1", "values": [0.1]}], namespace="kb") == {"upserted_count": 1}
        results = client.search("consulta", top_k=2, namespace="kb", filter={"state": "published"})
        client.delete(["v1"], namespace="kb")

    assert results[0]["metadata"]["article_id"] == "1"
    assert results[1]["metadata"] == {}
    index.query.assert_called_once_with(
        vector=[0.1, 0.2],
        top_k=2,
        namespace="kb",
        filter={"state": "published"},
        include_metadata=True,
    )
    index.delete.assert_called_once_with(ids=["v1"], namespace="kb")


def test_pinecone_client_propagates_provider_errors() -> None:
    index = Mock()
    index.upsert.side_effect = RuntimeError("upsert failed")
    with pytest.raises(RuntimeError):
        PineconeClient(index).upsert([])

    index.query.side_effect = RuntimeError("query failed")
    openai_client = Mock()
    openai_client.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1])])
    with patch("openai.OpenAI", return_value=openai_client), pytest.raises(RuntimeError):
        PineconeClient(index).search("consulta")


@override_settings(PINECONE_API_KEY="key", PINECONE_INDEX_NAME="index-name")
def test_pinecone_singleton_reuses_index() -> None:
    pinecone_module._pinecone_index = None
    index = Mock()
    sdk = Mock()
    sdk.Index.return_value = index
    with patch("pinecone.Pinecone", return_value=sdk) as factory:
        first = pinecone_module.get_pinecone_client()
        second = pinecone_module.get_pinecone_client()

    assert first._index is index
    assert second._index is index
    factory.assert_called_once_with(api_key="key")


@override_settings(SUPABASE_URL="", SUPABASE_SERVICE_KEY="")
def test_supabase_singleton_requires_configuration() -> None:
    supabase_module._supabase_client = None
    with pytest.raises(ValueError):
        supabase_module.get_supabase_client()


@override_settings(SUPABASE_URL="https://project.supabase.co", SUPABASE_SERVICE_KEY="service-key")
def test_supabase_singleton_reuses_client() -> None:
    supabase_module._supabase_client = None
    sentinel = Mock()
    with patch("apps.integrations.supabase_client.client.create_client", return_value=sentinel) as factory:
        assert supabase_module.get_supabase_client() is sentinel
        assert supabase_module.get_supabase_client() is sentinel
    factory.assert_called_once_with("https://project.supabase.co", "service-key")
