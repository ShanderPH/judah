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

from datetime import UTC

import structlog
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
    from django.db.models import F
    from django.db.models.functions import Coalesce

    eligible = list(
        Agent.objects.filter(
            status_enum=Agent.StatusEnum.ONLINE,
            auto_assign_enabled=True,
            current_simultaneous_chats__lt=Coalesce(F("max_simultaneous_chats"), 5),
        )
        .exclude(is_active=False)
        .only(
            "id",
            "name",
            "hubspot_owner_id",
            "status_enum",
            "current_simultaneous_chats",
            "max_simultaneous_chats",
            "last_assignment_at",
            "auto_assign_enabled",
            "is_active",
        )
    )

    logger.debug("queue_eligible_agents", count=len(eligible))
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
    _epoch = timezone.datetime(2000, 1, 1, tzinfo=UTC)

    def _sort_key(agent: Agent) -> tuple:
        last = agent.last_assignment_at or _epoch
        # Make timezone-aware if naive (handles legacy data)
        if timezone.is_naive(last):
            last = timezone.make_aware(last, UTC)
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

    Uses F() expressions to prevent race conditions when multiple workers
    try to increment the same agent's count simultaneously.

    Args:
        agent: The Agent instance to update.
    """
    from django.db.models import F

    now = timezone.now()
    Agent.objects.filter(pk=agent.pk).update(
        current_simultaneous_chats=F("current_simultaneous_chats") + 1,
        last_assignment_at=now,
        updated_at=now,
    )
    # Update in-memory instance for callers that check capacity after this call.
    agent.current_simultaneous_chats += 1
    agent.last_assignment_at = now


def decrement_agent_chat_count(agent: Agent) -> None:
    """Atomically decrement an agent's current simultaneous chat count (min 0).

    Uses Greatest() to ensure the count never goes below zero, even under
    concurrent updates.

    Args:
        agent: The Agent instance to update.
    """
    from django.db.models import F, Value
    from django.db.models.functions import Greatest

    Agent.objects.filter(pk=agent.pk).update(
        current_simultaneous_chats=Greatest(F("current_simultaneous_chats") - 1, Value(0)),
        updated_at=timezone.now(),
    )
    # Update in-memory instance to reflect the change.
    agent.current_simultaneous_chats = max(agent.current_simultaneous_chats - 1, 0)


def get_last_assigned_owner_id() -> int | None:
    """Return the hubspot_owner_id of the most recently auto-assigned agent.

    Used to enforce Rule 2 (no consecutive assignments).

    Returns:
        hubspot_owner_id of the last assigned agent, or None.
    """
    from apps.support.models import AssignmentLog

    last = (
        AssignmentLog.objects.filter(assignment_type="automatic", hubspot_owner_id__isnull=False)
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
    pending = NewConversation.objects.count()

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
