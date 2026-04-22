"""Tests for apps.integrations.jira schemas (pure pydantic)."""

from __future__ import annotations

from apps.integrations.jira.schemas import CreateJiraIssueRequest, JiraIssueSchema


class TestJiraIssueSchema:
    def test_minimal_roundtrip(self) -> None:
        issue = JiraIssueSchema(
            key="INCH-1",
            summary="Bug X",
            status="Open",
            priority="High",
            url="https://inchurch.atlassian.net/browse/INCH-1",
        )
        assert issue.key == "INCH-1"
        assert issue.priority == "High"


class TestCreateJiraIssueRequest:
    def test_defaults_applied(self) -> None:
        req = CreateJiraIssueRequest(summary="X", description="Y")
        assert req.issue_type == "Bug"
        assert req.priority == "Medium"
        assert req.project_key == "INCH"

    def test_overrides(self) -> None:
        req = CreateJiraIssueRequest(
            summary="X",
            description="Y",
            issue_type="Task",
            priority="Low",
            project_key="PROJ",
        )
        assert req.issue_type == "Task"
        assert req.project_key == "PROJ"
