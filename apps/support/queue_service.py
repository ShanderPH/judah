"""Queue service — ranked agent selection for auto-assignment.

Implements the 4-rule priority algorithm for selecting which agent
receives the next ticket:

Priority rules (1 = highest importance):
  1. Only ONLINE agents are eligible (AWAY/OFFLINE/BUSY are excluded).
  2. Never assign two consecutive tickets to the same agent
     (ignored when only one agent is online).
  3. Prefer the agent with the longest time since their last assignment
     (NULL last_assignment_at = highest priority).
  4. Among equally-eligible agents, prefer the one with the fewest
     current simultaneous chats; reject any who have reached their
     max_simultaneous_chats limit.
"""

from __future__ import annotations

import structlog
from datetime import timezone as dt_tz
from django.utils import timezone

from apps.support.models import Agent

logger = structlog.get_logger(__name__)


def get_eligible_agents() -> list[Agent]:
    """Return agents that can currently receive a ticket.

    Eligibility criteria:
    - status_enum == ONLINE
    - auto_assign_enabled == True (or NULL, treated as True)
    - is_active != False
    - current_simultaneous_chats < max_simultaneous_chats

    Returns:
        Queryset-evaluated list of eligible Agent instances.
    """
    agents = Agent.objects.filter(
        status_enum=Agent.StatusEnum.ONLINE,
        auto_assign_enabled=True,
    ).exclude(is_active=False)

    # Filter out agents at capacity
    eligible = [a for a in agents if a.current_simultaneous_chats < (a.max_simultaneous_chats or 5)]

    logger.debug("queue_eligible_agents", count=len(eligible), agent_ids=[str(a.id) for a in eligible])
    return eligible


def select_next_agent(last_assigned_hubspot_owner_id: int | None = None) -> Agent | None:
    """Select the best agent for the next ticket using the 4-rule priority.

    Args:
        last_assigned_hubspot_owner_id: The hubspot_owner_id of the agent who
            received the previous ticket. Used to avoid consecutive assignments
            (Rule 2). Pass None if there is no previous assignment.

    Returns:
        The selected Agent instance, or None if no eligible agent exists.
    """
    eligible = get_eligible_agents()

    if not eligible:
        logger.warning("queue_no_eligible_agents")
        return None

    # Rule 2: Exclude the last-assigned agent — unless they are the ONLY one.
    candidates = eligible
    if last_assigned_hubspot_owner_id is not None and len(eligible) > 1:
        candidates = [a for a in eligible if a.hubspot_owner_id != last_assigned_hubspot_owner_id]
        if not candidates:
            # Fallback: last-assigned is the only available agent; use full pool.
            candidates = eligible
            logger.info(
                "queue_rule2_fallback_single_agent",
                last_owner_id=last_assigned_hubspot_owner_id,
            )

    # Rule 3 + 4: Sort by (last_assignment_at ASC, current_simultaneous_chats ASC)
    # NULL last_assignment_at means never assigned → highest priority → sort None as epoch 0.
    _epoch = timezone.datetime(2000, 1, 1, tzinfo=dt_tz.utc)

    def _sort_key(agent: Agent) -> tuple:
        last = agent.last_assignment_at or _epoch
        # Make timezone-aware if naive (handles legacy data)
        if timezone.is_naive(last):
            last = timezone.make_aware(last, timezone.utc)
        return (last, agent.current_simultaneous_chats)

    candidates.sort(key=_sort_key)
    selected = candidates[0]

    logger.info(
        "queue_agent_selected",
        agent_id=str(selected.id),
        agent_name=selected.name,
        hubspot_owner_id=selected.hubspot_owner_id,
        current_chats=selected.current_simultaneous_chats,
        last_assignment_at=str(selected.last_assignment_at),
    )
    return selected


def increment_agent_chat_count(agent: Agent) -> None:
    """Atomically increment an agent's current simultaneous chat count.

    Args:
        agent: The Agent instance to update.
    """
    Agent.objects.filter(pk=agent.pk).update(
        current_simultaneous_chats=agent.current_simultaneous_chats + 1,
        last_assignment_at=timezone.now(),
        updated_at=timezone.now(),
    )
    # Refresh in-memory object
    agent.refresh_from_db()
    logger.debug(
        "queue_agent_chat_count_incremented",
        agent_id=str(agent.id),
        new_count=agent.current_simultaneous_chats,
    )


def decrement_agent_chat_count(agent: Agent) -> None:
    """Atomically decrement an agent's current simultaneous chat count (min 0).

    Called when a conversation is closed.

    Args:
        agent: The Agent instance to update.
    """
    Agent.objects.filter(pk=agent.pk).update(
        current_simultaneous_chats=max(0, agent.current_simultaneous_chats - 1),
        updated_at=timezone.now(),
    )
    agent.refresh_from_db()
    logger.debug(
        "queue_agent_chat_count_decremented",
        agent_id=str(agent.id),
        new_count=agent.current_simultaneous_chats,
    )


def get_last_assigned_owner_id() -> int | None:
    """Return the hubspot_owner_id of the most recently auto-assigned agent.

    Used to enforce Rule 2 (no consecutive assignments).

    Returns:
        hubspot_owner_id of the last assigned agent, or None.
    """
    from apps.support.models import AssignmentLog

    last = (
        AssignmentLog.objects.filter(assignment_type="auto", hubspot_owner_id__isnull=False)
        .order_by("-assigned_at")
        .values_list("hubspot_owner_id", flat=True)
        .first()
    )
    return last


def get_queue_status() -> dict:
    """Return a snapshot of the current assignment queue status.

    Returns:
        Dict with online agents, eligible agents, and queue depth.
    """
    from apps.support.models import NewConversation

    online = Agent.objects.filter(status_enum=Agent.StatusEnum.ONLINE)
    eligible = get_eligible_agents()
    pending = NewConversation.objects.filter(is_pending=True).count()

    return {
        "online_agents": online.count(),
        "eligible_agents": len(eligible),
        "pending_queue_depth": pending,
        "agents": [
            {
                "id": str(a.id),
                "name": a.name,
                "hubspot_owner_id": a.hubspot_owner_id,
                "status": a.status_enum,
                "current_chats": a.current_simultaneous_chats,
                "max_chats": a.max_simultaneous_chats,
                "last_assignment_at": a.last_assignment_at.isoformat() if a.last_assignment_at else None,
            }
            for a in online
        ],
    }
