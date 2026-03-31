"""Jira API client for JUDAH."""

from typing import Any

import structlog
from jira import JIRA

from common.circuit_breaker import CircuitBreaker
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)

_circuit_breaker = CircuitBreaker(name="jira", failure_threshold=5, recovery_timeout=60)


class JiraClient:
    """Typed wrapper around the Jira SDK for issue management."""

    def __init__(self, server: str, email: str, token: str) -> None:
        self._jira = JIRA(
            server=server,
            basic_auth=(email, token),
        )

    def search_issues(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Search Jira issues using a text query (JQL text search).

        Args:
            query: Text search string.
            max_results: Maximum number of results.

        Returns:
            List of dicts with key, summary, status, and priority.
        """
        try:
            jql = f'text ~ "{query}" ORDER BY created DESC'
            issues = _circuit_breaker.call(
                self._jira.search_issues,
                jql,
                maxResults=max_results,
            )
            return [
                {
                    "key": issue.key,
                    "summary": issue.fields.summary,
                    "status": issue.fields.status.name,
                    "priority": issue.fields.priority.name if issue.fields.priority else "None",
                    "url": f"{self._jira.server_url}/browse/{issue.key}",
                }
                for issue in issues
            ]
        except Exception as exc:
            logger.error("jira_search_failed", query=query[:50], error=str(exc))
            raise ExternalServiceError("Jira", str(exc)) from exc

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
            summary: Issue title.
            description: Detailed description.
            issue_type: Jira issue type name.
            priority: Jira priority name.
            project_key: Target project key.

        Returns:
            Dict with issue key and URL.
        """
        try:
            fields = {
                "project": {"key": project_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type},
                "priority": {"name": priority},
            }
            issue = _circuit_breaker.call(self._jira.create_issue, fields=fields)
            url = f"{self._jira.server_url}/browse/{issue.key}"
            logger.info("jira_issue_created", key=issue.key, url=url)
            return {"key": issue.key, "url": url}
        except Exception as exc:
            logger.error("jira_create_issue_failed", summary=summary[:50], error=str(exc))
            raise ExternalServiceError("Jira", str(exc)) from exc


_jira_client: JiraClient | None = None


def get_jira_client() -> JiraClient:
    """Return a shared JiraClient instance (singleton).

    Returns:
        Configured JiraClient.
    """
    global _jira_client
    if _jira_client is None:
        from django.conf import settings

        server = settings.JIRA_SERVER_URL
        email = settings.JIRA_USER_EMAIL
        token = settings.JIRA_API_TOKEN

        if not all([server, email, token]):
            raise ValueError("JIRA_SERVER_URL, JIRA_USER_EMAIL, and JIRA_API_TOKEN must be set.")

        _jira_client = JiraClient(server=server, email=email, token=token)
        logger.info("jira_client_initialized", server=server)
    return _jira_client
