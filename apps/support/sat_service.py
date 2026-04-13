"""SAT (Smart Agent Tracking) — real-time agent status and time tracking.

The SAT service runs as a 20-second Celery Beat heartbeat during business
hours.  It consolidates agent availability polling and introduces:

- Per-agent online/away time accumulation
- Faster status detection (20s vs. previous 3-minute polling)
- On-demand load reconciliation with HubSpot ticket counts
- Daily time log snapshots for productivity metrics

Architecture:
  ``sat_heartbeat()`` is the main entry point, called by ``task_sat_heartbeat``.
  It performs a single HubSpot API call to fetch all user availability, then
  updates local Agent records and triggers the Matchmaker when agents come online.

  ``sat_reconcile_agent_load()`` is called by the Matchmaker before each
  assignment to ensure the candidate agent's chat count matches HubSpot.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.support.agent_sync_service import is_business_hours

logger = structlog.get_logger(__name__)


def sat_heartbeat() -> dict:
    """Execute a single SAT heartbeat cycle.

    Steps:
      1. Early-exit if outside business hours (no API calls).
      2. Fetch all users' availability status from HubSpot (1 API call).
      3. For each active agent, compare remote status with local ``status_enum``.
      4. On status change: update agent, log history, accumulate time.
      5. If any agent transitioned to ONLINE, dispatch Matchmaker drain.

    Returns:
        Dict with ``agents_checked``, ``status_changes``, ``agents_came_online``,
        ``skipped_off_hours`` keys.
    """
    if not is_business_hours():
        return {
            "agents_checked": 0,
            "status_changes": 0,
            "agents_came_online": 0,
            "skipped_off_hours": True,
        }

    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.support.models import Agent, AgentStatusHistory

    client = get_hubspot_client()

    # Single API call for all availability
    try:
        availability_data = client.get_all_owners_availability()
    except Exception as exc:
        logger.warning("sat_heartbeat_availability_fetch_failed", error=str(exc))
        return {
            "agents_checked": 0,
            "status_changes": 0,
            "agents_came_online": 0,
            "skipped_off_hours": False,
            "error": str(exc),
        }

    availability_map: dict[str, str] = {
        item.get("email", "").lower(): item.get("status_enum", "away") for item in availability_data
    }

    # Get all active agents
    agents = list(
        Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True))
        .exclude(hubspot_owner_id__isnull=True)
        .order_by("id")
    )

    now = timezone.now()
    status_changes = 0
    agents_came_online = 0

    for agent in agents:
        email_lower = (agent.agent_email or "").lower()
        if email_lower not in availability_map:
            continue

        new_status = availability_map[email_lower]
        old_status = agent.status_enum

        # Always update heartbeat timestamp
        update_fields = ["sat_last_heartbeat_at", "updated_at"]
        agent.sat_last_heartbeat_at = now
        agent.updated_at = now

        if old_status != new_status:
            # Accumulate time in the old status before switching
            sat_accumulate_time(agent, old_status, new_status, now)

            agent.status_enum = new_status
            agent.last_status_change_at = now
            update_fields.extend(
                [
                    "status_enum",
                    "last_status_change_at",
                    "online_time_seconds_today",
                    "away_time_seconds_today",
                ]
            )

            AgentStatusHistory.objects.create(
                agent=agent,
                old_status=old_status,
                new_status=new_status,
                sync_source="sat_heartbeat",
            )

            status_changes += 1
            if new_status == "online":
                agents_came_online += 1

            logger.info(
                "sat_agent_status_changed",
                agent=agent.name,
                old_status=old_status,
                new_status=new_status,
            )

        agent.save(update_fields=update_fields)

    # If any agent came online, trigger Matchmaker to drain pending queue
    if agents_came_online > 0:
        try:
            from apps.support.tasks import task_matchmaker_drain_queue

            task_matchmaker_drain_queue.delay()
            logger.info("sat_triggered_matchmaker_drain", agents_came_online=agents_came_online)
        except Exception as exc:
            logger.warning("sat_matchmaker_dispatch_failed", error=str(exc))

    logger.info(
        "sat_heartbeat_done",
        agents_checked=len(agents),
        status_changes=status_changes,
        agents_came_online=agents_came_online,
    )

    return {
        "agents_checked": len(agents),
        "status_changes": status_changes,
        "agents_came_online": agents_came_online,
        "skipped_off_hours": False,
    }


def sat_reconcile_agent_load(agent) -> int:
    """Reconcile a single agent's chat count with HubSpot.

    Called by the Matchmaker before assigning a ticket to ensure the
    candidate has accurate capacity data.

    Args:
        agent: Agent instance to reconcile.

    Returns:
        The reconciled (authoritative) chat count from HubSpot.
    """
    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.support.models import Agent

    client = get_hubspot_client()

    try:
        hubspot_count = client.count_active_tickets_by_owner(agent.hubspot_owner_id)
    except Exception as exc:
        logger.warning(
            "sat_reconcile_load_failed",
            agent=agent.name,
            error=str(exc),
        )
        # Return local count as fallback
        return agent.current_simultaneous_chats

    if hubspot_count < 0:
        return agent.current_simultaneous_chats

    now = timezone.now()

    if agent.current_simultaneous_chats != hubspot_count:
        with transaction.atomic():
            Agent.objects.filter(pk=agent.pk).select_for_update().update(
                current_simultaneous_chats=hubspot_count,
                sat_last_count_sync_at=now,
                updated_at=now,
            )
        logger.info(
            "sat_agent_count_reconciled",
            agent=agent.name,
            local_count=agent.current_simultaneous_chats,
            hubspot_count=hubspot_count,
        )
        agent.current_simultaneous_chats = hubspot_count
    else:
        Agent.objects.filter(pk=agent.pk).update(
            sat_last_count_sync_at=now,
            updated_at=now,
        )

    agent.sat_last_count_sync_at = now
    return hubspot_count


def sat_accumulate_time(
    agent,
    old_status: str,
    new_status: str,
    now: datetime,
) -> None:
    """Accumulate time spent in the previous status.

    Calculates seconds since ``agent.last_status_change_at`` and adds to
    the appropriate daily counter on the Agent model. Also upserts the
    ``AgentDailyTimeLog`` for today.

    Args:
        agent: Agent instance (modified in-place, caller must save).
        old_status: The status the agent is leaving.
        new_status: The status the agent is entering (unused, for logging).
        now: Current timestamp.
    """
    from apps.support.models import AgentDailyTimeLog

    if not agent.last_status_change_at:
        # First time tracking — no delta to accumulate
        agent.last_status_change_at = now
        return

    delta_seconds = int((now - agent.last_status_change_at).total_seconds())
    if delta_seconds <= 0:
        return

    today = timezone.localdate()

    # Ensure the daily log row exists (F() expressions can only UPDATE, not INSERT)
    daily_log, _ = AgentDailyTimeLog.objects.get_or_create(
        agent=agent,
        log_date=today,
    )

    if old_status == "online":
        agent.online_time_seconds_today += delta_seconds
        AgentDailyTimeLog.objects.filter(pk=daily_log.pk).update(
            online_time_seconds=F("online_time_seconds") + delta_seconds,
            status_transitions=F("status_transitions") + 1,
        )
    elif old_status in ("away", "busy"):
        agent.away_time_seconds_today += delta_seconds
        AgentDailyTimeLog.objects.filter(pk=daily_log.pk).update(
            away_time_seconds=F("away_time_seconds") + delta_seconds,
            status_transitions=F("status_transitions") + 1,
        )

    logger.debug(
        "sat_time_accumulated",
        agent=agent.name,
        old_status=old_status,
        delta_seconds=delta_seconds,
    )


def sat_reset_daily_counters() -> dict:
    """Snapshot and reset daily time counters for all agents.

    Should run at midnight (00:01 AM). Ensures any remaining time in the
    current status is accumulated before resetting.

    Returns:
        Dict with ``agents_reset`` count.
    """
    from apps.support.models import Agent, AgentDailyTimeLog

    yesterday = timezone.localdate() - timezone.timedelta(days=1)
    now = timezone.now()

    agents = list(
        Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True)).exclude(hubspot_owner_id__isnull=True)
    )

    reset_count = 0

    for agent in agents:
        # Flush any pending time for the current status before reset
        if agent.last_status_change_at and agent.status_enum in ("online", "away", "busy"):
            delta_seconds = int((now - agent.last_status_change_at).total_seconds())
            if delta_seconds > 0:
                if agent.status_enum == "online":
                    agent.online_time_seconds_today += delta_seconds
                else:
                    agent.away_time_seconds_today += delta_seconds

        # Snapshot to daily log (for yesterday, since we run at 00:01)
        if agent.online_time_seconds_today > 0 or agent.away_time_seconds_today > 0:
            AgentDailyTimeLog.objects.update_or_create(
                agent=agent,
                log_date=yesterday,
                defaults={
                    "online_time_seconds": agent.online_time_seconds_today,
                    "away_time_seconds": agent.away_time_seconds_today,
                },
            )

        # Reset counters and anchor time
        agent.online_time_seconds_today = 0
        agent.away_time_seconds_today = 0
        agent.last_status_change_at = now
        agent.save(
            update_fields=[
                "online_time_seconds_today",
                "away_time_seconds_today",
                "last_status_change_at",
                "updated_at",
            ]
        )
        reset_count += 1

    logger.info("sat_daily_counters_reset", agents_reset=reset_count, snapshot_date=str(yesterday))
    return {"agents_reset": reset_count}
