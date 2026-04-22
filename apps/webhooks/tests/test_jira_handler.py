"""Tests for the minimal Jira webhook handler."""

from __future__ import annotations

from types import SimpleNamespace

from apps.webhooks.handlers.jira_handler import _handle_issue_event, handle_jira_event


def _event(event_type: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(event_type=event_type, payload=payload, pk=1)


class TestHandleJiraEvent:
    def test_issue_created_routes_to_issue_handler(self) -> None:
        event = _event(
            "jira:issue_created",
            {"issue": {"key": "INCH-1", "fields": {"status": {"name": "Open"}}}},
        )
        # Should not raise — just exercises the dispatch.
        handle_jira_event(event)

    def test_issue_updated_routes(self) -> None:
        event = _event(
            "jira:issue_updated",
            {"issue": {"key": "INCH-9", "fields": {"status": {"name": "In Progress"}}}},
        )
        handle_jira_event(event)

    def test_unhandled_event_type_logged_only(self) -> None:
        event = _event("jira:issue_deleted", {})
        handle_jira_event(event)


class TestHandleIssueEvent:
    def test_missing_fields_handled_gracefully(self) -> None:
        _handle_issue_event("jira:issue_created", {})

    def test_partial_payload(self) -> None:
        _handle_issue_event("jira:issue_updated", {"issue": {"key": "X-1"}})

    def test_full_payload_parsed(self) -> None:
        payload = {
            "issue": {
                "key": "X-7",
                "fields": {"status": {"name": "Done"}},
            }
        }
        _handle_issue_event("jira:issue_created", payload)
