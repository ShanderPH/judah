"""Service for synchronizing agent status and conversation counts from HubSpot.

This module provides optimized, concurrency-safe synchronization of agent data
with support for business hours scheduling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from apps.support.models import Agent

logger = structlog.get_logger(__name__)


# Business hours configuration (America/Sao_Paulo)
BUSINESS_HOURS = {
    0: None,  # Monday - will be overridden
    1: None,  # Tuesday - will be overridden
    2: None,  # Wednesday - will be overridden
    3: None,  # Thursday - will be overridden
    4: None,  # Friday - will be overridden
    5: (9, 13),  # Saturday: 9h às 13h
    6: (8, 12),  # Sunday: 8h às 12h
}

# Monday-Friday: 9h às 18h
for day in range(5):
    BUSINESS_HOURS[day] = (9, 18)


def is_business_hours() -> bool:
    """Check if current time is within business hours.

    Returns:
        True if within business hours, False otherwise.
    """
    now = timezone.localtime()
    hours = BUSINESS_HOURS.get(now.weekday())

    if hours is None:
        return False

    start_hour, end_hour = hours
    return start_hour <= now.hour < end_hour


def get_poll_interval_seconds() -> int:
    """Get the appropriate polling interval based on current time.

    Returns:
        30 seconds during business hours, 3600 seconds (1 hour) otherwise.
    """
    return 30 if is_business_hours() else 3600


def sync_all_agents_status_and_counts_optimized() -> dict:
    """Optimized sync of all agents' status and conversation counts.

    This function performs a parallel sync with:
    1. Concurrency-safe database updates using select_for_update()
    2. Batch API calls to minimize HubSpot API usage
    3. Proper handling of simultaneous agent updates

    Returns:
        Dict with ``agents_synced``, ``status_changes``, ``count_corrections``,
        ``api_calls_made`` keys.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.support.models import Agent, AgentStatusHistory

    client = get_hubspot_client()

    # Get all active agents from local DB with lock
    # Include agents with is_active=True or is_active=None (not False)
    # Use Q objects to properly handle NULL values
    from django.db.models import Q

    agents = list(
        Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True))
        .exclude(hubspot_owner_id__isnull=True)
        .order_by("id")
    )

    if not agents:
        logger.debug("sync_all_agents_no_active_agents")
        return {
            "agents_synced": 0,
            "status_changes": 0,
            "count_corrections": 0,
            "api_calls_made": 0,
        }

    # Single API call for all availability status
    api_calls_made = 1
    try:
        availability_data = client.get_all_owners_availability()
        availability_map = {
            item.get("email", "").lower(): item.get("status_enum", "away") for item in availability_data
        }
    except Exception as exc:
        logger.warning("sync_all_agents_availability_fetch_failed", error=str(exc))
        availability_map = {}

    # Fetch conversation counts in parallel (batched by agent)
    count_map: dict[int, int] = {}

    def fetch_count(agent: Agent) -> tuple[int, int] | None:
        try:
            count = client.count_active_tickets_by_owner(agent.hubspot_owner_id)
            return (agent.hubspot_owner_id, count)
        except Exception as exc:
            logger.warning(
                "sync_agent_count_fetch_error",
                agent=agent.name,
                owner_id=agent.hubspot_owner_id,
                error=str(exc),
            )
            return None

    # Use ThreadPoolExecutor for parallel API calls
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_count, agent): agent for agent in agents}
        for future in as_completed(futures):
            result = future.result()
            if result:
                owner_id, count = result
                if count >= 0:  # -1 indicates error
                    count_map[owner_id] = count

    api_calls_made += len([a for a in agents if a.hubspot_owner_id])

    # Concurrency-safe batch updates
    status_changes = 0
    count_corrections = 0
    now = timezone.now()

    # Process updates in batches with database locking
    agent_ids = [agent.id for agent in agents if agent.id]
    batch_size = 10

    for i in range(0, len(agent_ids), batch_size):
        batch_ids = agent_ids[i : i + batch_size]

        with transaction.atomic():
            # Lock this batch of agents
            locked_agents = {
                a.id: a for a in Agent.objects.filter(id__in=batch_ids).select_for_update(nowait=False).order_by("id")
            }

            for agent_id in batch_ids:
                agent = locked_agents.get(agent_id)
                if not agent:
                    continue

                updates = []
                email_lower = (agent.agent_email or "").lower()

                # Update status from availability map
                if email_lower in availability_map:
                    new_status = availability_map[email_lower]
                    if agent.status_enum != new_status:
                        old_status = agent.status_enum
                        agent.status_enum = new_status
                        updates.append("status_enum")
                        status_changes += 1

                        # Log status change
                        AgentStatusHistory.objects.create(
                            agent=agent,
                            old_status=old_status,
                            new_status=new_status,
                            sync_source="hubspot_poll_optimized",
                        )
                        logger.info(
                            "sync_agent_status_updated",
                            agent=agent.name,
                            old_status=old_status,
                            new_status=new_status,
                        )

                # Update conversation count from HubSpot
                if agent.hubspot_owner_id in count_map:
                    hubspot_count = count_map[agent.hubspot_owner_id]
                    if agent.current_simultaneous_chats != hubspot_count:
                        old_count = agent.current_simultaneous_chats
                        agent.current_simultaneous_chats = hubspot_count
                        updates.append("current_simultaneous_chats")
                        count_corrections += 1
                        logger.info(
                            "sync_agent_count_corrected",
                            agent=agent.name,
                            old_count=old_count,
                            new_count=hubspot_count,
                            owner_id=agent.hubspot_owner_id,
                        )

                if updates:
                    agent.updated_at = now
                    updates.append("updated_at")
                    agent.save(update_fields=updates)

    logger.info(
        "sync_all_agents_complete",
        agents_synced=len(agents),
        status_changes=status_changes,
        count_corrections=count_corrections,
        api_calls_made=api_calls_made,
        business_hours=is_business_hours(),
    )

    return {
        "agents_synced": len(agents),
        "status_changes": status_changes,
        "count_corrections": count_corrections,
        "api_calls_made": api_calls_made,
    }


def reschedule_agent_status_task() -> dict:
    """Reschedule the agent status polling task based on business hours.

    This function should be called periodically to adjust the polling interval
    based on whether it's currently business hours or not.

    Returns:
        Dict with ``interval_seconds``, ``is_business_hours``, ``next_run``.
    """
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    interval_seconds = get_poll_interval_seconds()

    # Get or create the appropriate interval schedule
    schedule, created = IntervalSchedule.objects.get_or_create(
        every=interval_seconds,
        period=IntervalSchedule.SECONDS,
    )

    # Update the periodic task
    task, _ = PeriodicTask.objects.update_or_create(
        name="poll-hubspot-agent-status",
        defaults={
            "interval": schedule,
            "task": "support.task_poll_hubspot_agent_status_dynamic",
            "enabled": True,
        },
    )

    result = {
        "interval_seconds": interval_seconds,
        "is_business_hours": is_business_hours(),
        "next_run": task.last_run_at + timezone.timedelta(seconds=interval_seconds) if task.last_run_at else None,
        "schedule_created": created,
    }

    logger.info("agent_status_task_rescheduled", **result)
    return result
