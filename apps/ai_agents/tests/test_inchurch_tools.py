"""Tests for the internal InRadar diagnostics toolkit."""

from unittest.mock import Mock, patch

from apps.ai_agents.tools.inchurch_tools import InChurchDiagnosticsTool


def _client_with(response: Mock):
    context = Mock()
    context.__enter__ = Mock(return_value=Mock(post=Mock(return_value=response)))
    context.__exit__ = Mock(return_value=False)
    return context


def test_diagnostics_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("INRADAR_AUTH_TOKEN", raising=False)
    assert "Token de autenticação" in InChurchDiagnosticsTool().diagnose_event_visibility(1)


def test_diagnostics_handles_not_found_and_provider_status(monkeypatch) -> None:
    monkeypatch.setenv("INRADAR_AUTH_TOKEN", "token")
    response = Mock(status_code=404)
    with patch("apps.ai_agents.tools.inchurch_tools.httpx.Client", return_value=_client_with(response)):
        assert "não foi encontrado" in InChurchDiagnosticsTool().diagnose_event_visibility(1)

    response = Mock(status_code=503)
    with patch("apps.ai_agents.tools.inchurch_tools.httpx.Client", return_value=_client_with(response)):
        assert "status 503" in InChurchDiagnosticsTool().diagnose_event_visibility(1)


def test_diagnostics_reports_healthy_and_problematic_events(monkeypatch) -> None:
    monkeypatch.setenv("INRADAR_AUTH_TOKEN", "token")
    healthy = Mock(
        status_code=200,
        json=Mock(
            return_value={
                "is_active": True,
                "is_enabled": True,
                "published_for": "todos",
                "has_active_tickets": True,
            }
        ),
    )
    with patch("apps.ai_agents.tools.inchurch_tools.httpx.Client", return_value=_client_with(healthy)):
        assert "Evento OK" in InChurchDiagnosticsTool().diagnose_event_visibility(1)

    problematic = Mock(
        status_code=200,
        json=Mock(
            return_value={
                "is_active": False,
                "is_enabled": False,
                "published_for": "membros",
                "has_active_tickets": False,
            }
        ),
    )
    with patch("apps.ai_agents.tools.inchurch_tools.httpx.Client", return_value=_client_with(problematic)):
        result = InChurchDiagnosticsTool().diagnose_event_visibility(2)
    assert "Problemas Encontrados" in result
    assert "desabilitado" in result
    assert "não possui ingressos" in result


def test_diagnostics_handles_transport_exception(monkeypatch) -> None:
    monkeypatch.setenv("INRADAR_AUTH_TOKEN", "token")
    with patch("apps.ai_agents.tools.inchurch_tools.httpx.Client", side_effect=RuntimeError("offline")):
        assert "erro de comunicação" in InChurchDiagnosticsTool().diagnose_event_visibility(1)
