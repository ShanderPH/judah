"""Tests for integration service orchestration."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.integrations.hubspot.services import sync_ticket_to_hubspot
from apps.integrations.jira.services import escalate_ticket_to_jira


def test_sync_ticket_to_hubspot_updates_local_ticket() -> None:
    ticket = SimpleNamespace(subject="Falha no login", priority="high", save=Mock())
    client = Mock()
    client.create_ticket.return_value = {"id": "hubspot-1"}
    with (
        patch("apps.support.models.Ticket.objects.get", return_value=ticket),
        patch("apps.integrations.hubspot.services.get_hubspot_client", return_value=client),
    ):
        assert sync_ticket_to_hubspot(1) == "hubspot-1"

    assert ticket.hubspot_ticket_id == "hubspot-1"
    ticket.save.assert_called_once_with(update_fields=["hubspot_ticket_id", "updated_at"])


def test_sync_ticket_to_hubspot_returns_none_on_failure() -> None:
    with patch("apps.support.models.Ticket.objects.get", side_effect=RuntimeError("db")):
        assert sync_ticket_to_hubspot(1) is None


def test_escalate_ticket_to_jira_maps_priority() -> None:
    client = Mock()
    client.create_issue.return_value = {"key": "INCH-1"}
    with (
        patch(
            "apps.support.models.Ticket.objects.get",
            return_value=SimpleNamespace(subject="Falha", priority="urgent"),
        ),
        patch("apps.integrations.jira.services.get_jira_client", return_value=client),
    ):
        assert escalate_ticket_to_jira(1, "Detalhes") == "INCH-1"

    client.create_issue.assert_called_once_with(
        summary="Falha",
        description="Detalhes",
        issue_type="Bug",
        priority="High",
    )


def test_escalate_ticket_to_jira_returns_none_on_failure() -> None:
    with patch("apps.support.models.Ticket.objects.get", side_effect=RuntimeError("db")):
        assert escalate_ticket_to_jira(1, "Detalhes") is None
