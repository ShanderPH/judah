"""Pydantic schemas for Jira integration."""

from ninja import Schema


class JiraIssueSchema(Schema):
    """Jira issue representation."""

    key: str
    summary: str
    status: str
    priority: str
    url: str


class CreateJiraIssueRequest(Schema):
    """Payload to create a Jira issue."""

    summary: str
    description: str
    issue_type: str = "Bug"
    priority: str = "Medium"
    project_key: str = "INCH"
