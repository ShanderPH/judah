"""Tests for base-agent configuration and MCP action helpers."""

from typing import Any, cast
from unittest.mock import patch

from django.test import override_settings

from apps.ai_agents.agents import action, base
from apps.ai_agents.agents.action import MCPServerConfig


def test_openai_model_redis_and_fallback_builders(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("OPENAI_ORG_ID", "org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "project")
    with patch("apps.ai_agents.agents.base.OpenAIChat", side_effect=lambda **kwargs: kwargs):
        primary = cast(dict[str, Any], base.build_primary_model())
        mini = cast(dict[str, Any], base.build_mini_model())
        assert primary["id"] == base.DEFAULT_MODEL_ID
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


@override_settings(DEBUG=False)
def test_base_agent_injects_defaults() -> None:
    model = SimpleModel("primary")
    fallback = object()
    database = object()

    def fake_init(instance, *, session_id, **kwargs):
        instance.session_id = session_id
        instance.name = kwargs.get("name", "Base")
        instance.model = kwargs["model"]
        instance.received_kwargs = kwargs

    with (
        patch("apps.ai_agents.agents.base.build_primary_model", return_value=model),
        patch("apps.ai_agents.agents.base._build_fallback_config", return_value=fallback),
        patch("apps.ai_agents.agents.base._build_redis_db", return_value=database),
        patch("agno.agent.Agent.__init__", new=fake_init),
    ):
        agent = base.BaseInChurchAgent("session", {"user_id": 1})

    assert agent.received_kwargs["fallback_config"] is fallback
    assert agent.received_kwargs["db"] is database
    assert agent.received_kwargs["debug_mode"] is False


class SimpleModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


def test_mcp_connectors_and_config_builder() -> None:
    with patch("apps.ai_agents.agents.action.MCPTools", side_effect=lambda **kwargs: kwargs):
        hubspot = cast(dict[str, Any], action.connect_hubspot_mcp("https://hub"))
        jira = cast(dict[str, Any], action.connect_jira_mcp("https://jira"))
        n8n = cast(dict[str, Any], action.connect_n8n_mcp("https://n8n"))
        helpdesk = cast(dict[str, Any], action.connect_helpdesk_api_mcp("https://help"))
        assert hubspot["tool_name_prefix"] == "hubspot"
        assert jira["tool_name_prefix"] == "jira"
        assert n8n["timeout_seconds"] == 45
        assert helpdesk["tool_name_prefix"] == "helpdesk"
        tools = cast(
            list[dict[str, Any]],
            action.build_mcp_tools_from_config(
                [
                    MCPServerConfig(name="disabled", enabled=False),
                    MCPServerConfig(name="missing"),
                    MCPServerConfig(name="stdio", command="python server.py", transport="stdio", env={"A": "B"}),
                    MCPServerConfig(name="sse", url="https://example"),
                ]
            ),
        )

    assert len(tools) == 2
    assert tools[0]["command"] == "python server.py"
    assert tools[0]["env"] == {"A": "B"}
    assert "hubspot_server.py" in action._get_hubspot_mcp_command()


def test_static_fallback_tools() -> None:
    with (
        patch("apps.ai_agents.agents.tools.hubspot_tools.GetTicketInfo", return_value="hubspot"),
        patch("apps.ai_agents.agents.tools.jira_tools.SearchJiraIssues", return_value="jira"),
        patch("apps.ai_agents.tools.inchurch_tools.InChurchDiagnosticsTool", return_value="diagnostics"),
    ):
        assert action._build_static_fallback_tools() == ["hubspot", "jira", "diagnostics"]
