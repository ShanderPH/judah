"""Jira integration service layer."""

import structlog

from apps.integrations.jira.client import get_jira_client

logger = structlog.get_logger(__name__)


def escalate_ticket_to_jira(ticket_id: int, description: str) -> str | None:
    """Create a Jira issue from a support ticket for bug escalation.

    Args:
        ticket_id: Local Ticket primary key.
        description: Detailed bug/issue description.

    Returns:
        Jira issue key if created successfully, else None.
    """
    from apps.support.models import Ticket

    try:
        ticket = Ticket.objects.get(pk=ticket_id)
        client = get_jira_client()
        result = client.create_issue(
            summary=ticket.subject,
            description=description,
            issue_type="Bug",
            priority="High" if ticket.priority in ("high", "urgent") else "Medium",
        )
        logger.info("ticket_escalated_to_jira", ticket_id=ticket_id, jira_key=result["key"])
        return result["key"]
    except Exception as exc:
        logger.error("ticket_escalate_to_jira_failed", ticket_id=ticket_id, error=str(exc))
        return None
