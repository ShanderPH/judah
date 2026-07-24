"""Tests for the local MCP diagnostic management command."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management.base import OutputWrapper

from apps.ai_agents.management.commands.test_mcp import Command


def _command() -> tuple[Command, StringIO]:
    stream = StringIO()
    command = Command()
    command.stdout = OutputWrapper(stream)
    return command, stream


def test_command_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    command, stream = _command()
    command.handle()
    assert "HUBSPOT_ACCESS_TOKEN" in stream.getvalue()


def test_command_handles_server_start_failure(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    process = MagicMock()
    process.poll.return_value = 1
    process.communicate.return_value = ("", "startup failed")
    command, stream = _command()
    with (
        patch("apps.ai_agents.management.commands.test_mcp.subprocess.Popen", return_value=process),
        patch("apps.ai_agents.management.commands.test_mcp.time.sleep"),
    ):
        command.handle()
    assert "startup failed" in stream.getvalue()


def test_command_handles_process_exception(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    command, stream = _command()
    with patch(
        "apps.ai_agents.management.commands.test_mcp.subprocess.Popen",
        side_effect=OSError("cannot spawn"),
    ):
        command.handle()
    assert "cannot spawn" in stream.getvalue()


def test_command_success(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    process = MagicMock()
    process.poll.return_value = None
    mcp_tool = MagicMock()
    agent = SimpleNamespace(name="Helpdesk Action")
    command, stream = _command()
    with (
        patch("apps.ai_agents.management.commands.test_mcp.subprocess.Popen", return_value=process),
        patch("apps.ai_agents.management.commands.test_mcp.time.sleep"),
        patch("agno.tools.mcp.MCPTools", return_value=mcp_tool),
        patch("apps.ai_agents.agents.action.HelpdeskActionAgent", return_value=agent),
    ):
        command.handle()
    output = stream.getvalue()
    assert "Servidor MCP iniciado" in output
    assert "Imports OK" in output
    assert "MCPTools OK" in output
    assert "Helpdesk Action" in output
    process.terminate.assert_called_once()


def test_command_handles_mcp_and_agent_construction_errors(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    process = MagicMock()
    process.poll.return_value = None

    command, stream = _command()
    with (
        patch("apps.ai_agents.management.commands.test_mcp.subprocess.Popen", return_value=process),
        patch("apps.ai_agents.management.commands.test_mcp.time.sleep"),
        patch("agno.tools.mcp.MCPTools", side_effect=RuntimeError("mcp unavailable")),
    ):
        command.handle()
    assert "mcp unavailable" in stream.getvalue()

    command, stream = _command()
    with (
        patch("apps.ai_agents.management.commands.test_mcp.subprocess.Popen", return_value=process),
        patch("apps.ai_agents.management.commands.test_mcp.time.sleep"),
        patch("agno.tools.mcp.MCPTools", return_value=MagicMock()),
        patch("apps.ai_agents.agents.action.HelpdeskActionAgent", side_effect=RuntimeError("agent unavailable")),
    ):
        command.handle()
    assert "agent unavailable" in stream.getvalue()
