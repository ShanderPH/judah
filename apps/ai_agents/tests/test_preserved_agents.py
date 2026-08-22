"""Coverage for independent AI capabilities intentionally kept after removal."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from apps.ai_agents.agents import base
from apps.ai_agents.agents.tools.hubspot_tools import GetTicketInfo
from apps.ai_agents.agents.tools.knowledge_tools import SearchKnowledgeBase
from apps.ai_agents.services.channel_capabilities import normalize_channel


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


def test_knowledge_tool_normalizes_results_and_errors() -> None:
    results = [SimpleNamespace(article_id="a1", title="Article", summary="Summary", score=0.95)]
    with patch("apps.knowledge.services.semantic_search", return_value=results):
        assert SearchKnowledgeBase().search("query", top_k=1) == [
            {"article_id": "a1", "title": "Article", "summary": "Summary", "score": 0.95}
        ]

    with patch("apps.knowledge.services.semantic_search", side_effect=RuntimeError("offline")):
        assert SearchKnowledgeBase().search("query") == []


def test_model_redis_and_fallback_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("OPENAI_ORG_ID", "org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "project")
    with patch("apps.ai_agents.agents.base.OpenAIResponses", side_effect=lambda **kwargs: kwargs):
        primary = cast(dict[str, Any], base.build_primary_model())
        mini = cast(dict[str, Any], base.build_mini_model())
    assert primary["id"] == base.DEFAULT_MODEL_ID
    assert primary["reasoning"] == {"effort": "xhigh"}
    assert mini["api_key"] == "key"

    with patch("apps.ai_agents.agents.base.RedisDb", return_value="redis") as redis_db:
        assert base._build_redis_db("session") == "redis"
    assert redis_db.call_args.kwargs["db_prefix"] == "inchurch:agent:session"

    with (
        patch("apps.ai_agents.agents.base.build_mini_model", return_value="mini"),
        patch("apps.ai_agents.agents.base.FallbackConfig", return_value="fallback") as fallback,
    ):
        assert base._build_fallback_config() == "fallback"
    fallback.assert_called_once_with(on_error=["mini"], on_rate_limit=["mini"])


def test_shared_redis_client_builds_a_bounded_pool() -> None:
    base._shared_redis_client.cache_clear()
    with (
        patch("apps.ai_agents.agents.base.redis.BlockingConnectionPool.from_url", return_value="pool") as pool,
        patch("apps.ai_agents.agents.base.redis.Redis", return_value="client") as client,
    ):
        assert base._shared_redis_client("redis://local/0", 3) == "client"
    pool.assert_called_once()
    client.assert_called_once_with(connection_pool="pool")
    base._shared_redis_client.cache_clear()


def test_invalid_reasoning_effort_fails_fast() -> None:
    with (
        patch.object(base, "DEFAULT_REASONING_EFFORT", "extreme"),
        pytest.raises(ValueError, match="OPENAI_REASONING_EFFORT"),
    ):
        base.build_primary_model()


@override_settings(DEBUG=False)
def test_base_agent_injects_independent_defaults() -> None:
    model = SimpleNamespace(id="primary")

    def fake_init(instance: object, *, session_id: str, **kwargs: Any) -> None:
        instance.session_id = session_id  # type: ignore[attr-defined]
        instance.name = "Base"  # type: ignore[attr-defined]
        instance.model = kwargs["model"]  # type: ignore[attr-defined]
        instance.received_kwargs = kwargs  # type: ignore[attr-defined]

    with (
        patch("apps.ai_agents.agents.base.build_primary_model", return_value=model),
        patch("apps.ai_agents.agents.base._build_fallback_config", return_value="fallback"),
        patch("apps.ai_agents.agents.base._build_redis_db", return_value="database"),
        patch("agno.agent.Agent.__init__", new=fake_init),
    ):
        agent = base.BaseInChurchAgent("session", {"user_id": 1})

    assert agent.received_kwargs["fallback_config"] == "fallback"  # type: ignore[attr-defined]
    assert agent.received_kwargs["db"] == "database"  # type: ignore[attr-defined]
    assert agent.received_kwargs["debug_mode"] is False  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "unknown"),
        ("", "unknown"),
        ("WhatsApp", "whatsapp"),
        ("WABA", "whatsapp"),
        ("WebChat", "chat"),
        ("mail", "email"),
        ("HubSpot", "hubspot"),
        ("WEB-CHAT", "web-chat"),
    ],
)
def test_channel_normalization(raw: object, expected: str) -> None:
    assert normalize_channel(raw) == expected


def test_agentos_registers_only_independent_agents() -> None:
    from apps.ai_agents import agent_os

    assert agent_os.agent_os.teams == []
    assert agent_os._agentos_user_metadata()["originating_channel"] == "webchat_central"
    with (
        patch.object(agent_os, "SalomaoChatAgent", return_value="adapter") as adapter,
        patch.object(agent_os, "agentos_db", "db"),
    ):
        assert agent_os.build_agentos_salomao_chat(None) == "adapter"
    assert adapter.call_args.kwargs["db"] == "db"
