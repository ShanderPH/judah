"""Handler for Jira webhook events."""

import structlog

logger = structlog.get_logger(__name__)


def handle_jira_event(event) -> None:
    """Route and process a Jira webhook event.

    Args:
        event: WebhookEvent instance with source=jira.
    """
    event_type: str = event.event_type
    payload: dict = event.payload

    logger.info("jira_event_received", event_type=event_type, event_id=event.pk)

    if event_type in ("jira:issue_created", "jira:issue_updated"):
        _handle_issue_event(event_type, payload)
    else:
        logger.debug("jira_event_unhandled", event_type=event_type)


def _handle_issue_event(event_type: str, payload: dict) -> None:
    """Process Jira issue events."""
    issue = payload.get("issue", {})
    issue_key = issue.get("key", "")
    status = issue.get("fields", {}).get("status", {}).get("name", "")

    logger.info("jira_issue_event", event_type=event_type, key=issue_key, status=status)
