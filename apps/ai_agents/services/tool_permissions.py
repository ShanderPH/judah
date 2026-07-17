"""State-based permissions for helpdesk tools with side effects."""

from __future__ import annotations

from apps.ai_agents.models import ConversationInstance

TOOL_PERMISSIONS_BY_STATE: dict[str, set[str]] = {
    ConversationInstance.State.CONTACT_COLLECTING: {"send_message"},
    ConversationInstance.State.CONTACT_ASSOCIATING: {
        "search_contact",
        "create_contact",
        "associate_contact",
    },
    ConversationInstance.State.AI_SERVICE_RUNNING: {
        "search_knowledge",
        "send_message",
        "add_internal_note",
    },
    ConversationInstance.State.HUMAN_HANDOFF_REQUESTED: {
        "add_internal_note",
        "move_ticket",
        "enqueue_assignment",
    },
    # The handoff is already durable at this point; this permission exists
    # solely for its idempotent confirmation message.
    ConversationInstance.State.QUEUE_PENDING: {"send_message"},
}

TOOL_ALIASES: dict[str, str] = {
    "send_thread_reply": "send_message",
    "assign_ticket_to_human_queue": "enqueue_assignment",
    "update_ticket_stage": "move_ticket",
}


def normalize_tool_name(tool_name: str) -> str:
    """Normalize tool/action names before permission checks."""
    normalized = tool_name.strip().lower()
    return TOOL_ALIASES.get(normalized, normalized)


def allowed_tools_for_state(state: str) -> set[str]:
    """Return the allowed tool names for a lifecycle state."""
    if state in {
        ConversationInstance.State.CLOSED,
        ConversationInstance.State.FAILED_TERMINAL,
        ConversationInstance.State.IGNORED,
    }:
        return set()
    return set(TOOL_PERMISSIONS_BY_STATE.get(state, set()))


def is_tool_allowed(state: str, tool_name: str) -> bool:
    """Return whether a tool may execute in the given lifecycle state."""
    return normalize_tool_name(tool_name) in allowed_tools_for_state(state)


__all__ = ["allowed_tools_for_state", "is_tool_allowed", "normalize_tool_name"]
