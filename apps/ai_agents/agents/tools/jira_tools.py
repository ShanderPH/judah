"""Agno tools for interacting with Jira issue tracker."""

from typing import Any

import structlog
from agno.tools import Toolkit

logger = structlog.get_logger(__name__)


class SearchJiraIssues(Toolkit):
    """Search and create issues in Jira."""

    def __init__(self) -> None:
        super().__init__(name="jira_tools")
        self.register(self.search_issues)
        self.register(self.create_issue)

    def search_issues(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Search Jira issues using a text query.

        Args:
            query: Text to search for in issue summaries and descriptions.
            max_results: Maximum number of results to return (default 10).

        Returns:
            List of dicts with issue key, summary, status, and priority.
        """
        try:
            from apps.integrations.jira.client import get_jira_client

            client = get_jira_client()
            return client.search_issues(query=query, max_results=max_results)
        except Exception as exc:
            logger.error("jira_search_failed", query=query, error=str(exc))
            return []

    def create_issue(
        self,
        summary: str,
        description: str,
        issue_type: str = "Bug",
        priority: str = "Medium",
        project_key: str = "INCH",
    ) -> dict[str, Any]:
        """Create a new Jira issue.

        Args:
            summary: Issue title/summary.
            description: Detailed issue description.
            issue_type: Type of issue (Bug, Task, Story, etc.).
            priority: Issue priority (Lowest, Low, Medium, High, Highest).
            project_key: Jira project key (default INCH).

        Returns:
            Dict with issue key and URL.
        """
        try:
            from apps.integrations.jira.client import get_jira_client

            client = get_jira_client()
            return client.create_issue(
                summary=summary,
                description=description,
                issue_type=issue_type,
                priority=priority,
                project_key=project_key,
            )
        except Exception as exc:
            logger.error("jira_create_issue_failed", summary=summary, error=str(exc))
            return {"error": str(exc)}
