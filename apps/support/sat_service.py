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
from django.conf import settings
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
    if not settings.AGENT_STATUS_SYNC_ENABLED:
        logger.debug("sat_heartbeat_status_sync_disabled")
        return {
            "agents_checked": 0,
            "status_changes": 0,
            "agents_came_online": 0,
            "skipped_off_hours": False,
            "skipped_status_sync_disabled": True,
        }

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

    # Get all active agents — only fetch fields needed for heartbeat logic
    agents = list(
        Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True))
        .exclude(hubspot_owner_id__isnull=True)
        .only(
            "id",
            "name",
            "agent_email",
            "status_enum",
            "sat_last_heartbeat_at",
            "last_status_change_at",
            "online_time_seconds_today",
            "away_time_seconds_today",
            "updated_at",
        )
        .order_by("id")
    )

    now = timezone.now()
    status_changes = 0
    agents_came_online = 0

    # Diagnostic: identify agents whose emails are NOT in the HubSpot Users API.
    # These agents rely exclusively on contact.propertyChange webhooks for status
    # updates. If their webhook email doesn't match agent_email in the DB, their
    # status can get stuck.
    unmatched_emails = [
        (a.agent_email or "N/A") for a in agents if (a.agent_email or "").lower() not in availability_map
    ]
    if unmatched_emails:
        logger.warning(
            "sat_heartbeat_agents_not_in_users_api",
            count=len(unmatched_emails),
            emails=unmatched_emails,
            users_api_emails=list(availability_map.keys()),
            hint=(
                "These agents are invisible to the SAT heartbeat. "
                "Verify their hs_email in HubSpot matches agent_email in the DB, "
                "and that they appear in GET /crm/v3/objects/users."
            ),
        )

    # Separate agents into heartbeat-only (no status change) and status-changed
    # so we can bulk_update the common case and individual-save only the exceptions.
    heartbeat_only_agents: list[Agent] = []
    status_history_rows: list[AgentStatusHistory] = []

    for agent in agents:
        email_lower = (agent.agent_email or "").lower()
        if email_lower not in availability_map:
            continue

        new_status = availability_map[email_lower]
        old_status = agent.status_enum

        # Always update heartbeat timestamp
        agent.sat_last_heartbeat_at = now
        agent.updated_at = now

        if old_status != new_status:
            # Accumulate time in the old status before switching
            sat_accumulate_time(agent, old_status, new_status, now)

            agent.status_enum = new_status
            agent.last_status_change_at = now

            status_history_rows.append(
                AgentStatusHistory(
                    agent=agent,
                    old_status=old_status,
                    new_status=new_status,
                    sync_source="sat_heartbeat",
                )
            )

            # Status-changed agents need extra fields saved
            agent.save(
                update_fields=[
                    "sat_last_heartbeat_at",
                    "updated_at",
                    "status_enum",
                    "last_status_change_at",
                    "online_time_seconds_today",
                    "away_time_seconds_today",
                ]
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
        else:
            heartbeat_only_agents.append(agent)

    # Bulk update heartbeat-only agents in a single query instead of N individual saves
    if heartbeat_only_agents:
        Agent.objects.bulk_update(
            heartbeat_only_agents,
            ["sat_last_heartbeat_at", "updated_at"],
            batch_size=50,
        )

    # Bulk create status history rows
    if status_history_rows:
        AgentStatusHistory.objects.bulk_create(status_history_rows)

    # If any agent came online, trigger Matchmaker to drain pending queue
    # Use a Redis guard to avoid thundering herd when multiple agents come
    # online in the same heartbeat cycle.
    if agents_came_online > 0:
        try:
            from django.core.cache import cache

            from apps.support.tasks import task_matchmaker_drain_queue

            drain_guard = "sat_drain_guard"
            if cache.add(drain_guard, "1", timeout=10):
                task_matchmaker_drain_queue.delay()
                logger.info("sat_triggered_matchmaker_drain", agents_came_online=agents_came_online)
            else:
                logger.debug("sat_drain_already_dispatched", agents_came_online=agents_came_online)
        except Exception as exc:
            logger.warning("sat_matchmaker_dispatch_failed", error=str(exc))

    # Log a concise heartbeat summary — only query pending count when
    # there were status changes (avoids a DB round-trip every 20 seconds).
    online_count = sum(1 for a in agents if a.status_enum == "online")

    if status_changes > 0:
        from apps.support.models import NewConversation

        pending_count = NewConversation.objects.exclude(queue_status=NewConversation.QueueStatus.FAILED).count()
        logger.info(
            "sat_heartbeat_done",
            agents_checked=len(agents),
            agents_online=online_count,
            status_changes=status_changes,
            agents_came_online=agents_came_online,
            pending_queue=pending_count,
        )
    else:
        logger.debug(
            "sat_heartbeat_done",
            agents_checked=len(agents),
            agents_online=online_count,
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

    Uses a "never reset downward" policy to prevent the TOCTOU race condition
    where HubSpot's count API lags behind recent assignments. If HubSpot shows
    a lower count than our local DB (due to propagation latency), we keep the
    local count. HubSpot corrections upward (e.g. manual assignments we missed)
    are always honoured. The periodic ``task_reconcile_agent_counts`` task (hourly)
    performs full authoritative correction in both directions.

    Args:
        agent: Agent instance to reconcile.

    Returns:
        The effective chat count to use for capacity decisions.
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
        # Return local count as fallback — do not reset to zero on transient errors
        return agent.current_simultaneous_chats

    if hubspot_count < 0:
        return agent.current_simultaneous_chats

    now = timezone.now()
    local_count = agent.current_simultaneous_chats

    # TOCTOU guard: only accept a downward correction if HubSpot shows strictly
    # MORE tickets than we track locally (e.g. a manual assignment we missed).
    # If HubSpot shows LESS (API latency after a recent auto-assignment), trust
    # the local count which was just incremented by increment_agent_chat_count().
    if hubspot_count > local_count:
        # HubSpot has more — sync upward
        effective_count = hubspot_count
        with transaction.atomic():
            Agent.objects.filter(pk=agent.pk).select_for_update().update(
                current_simultaneous_chats=effective_count,
                sat_last_count_sync_at=now,
                updated_at=now,
            )
        logger.info(
            "sat_agent_count_reconciled_upward",
            agent=agent.name,
            local_count=local_count,
            hubspot_count=hubspot_count,
            effective_count=effective_count,
        )
        agent.current_simultaneous_chats = effective_count
    elif hubspot_count < local_count:
        # HubSpot shows less — likely API latency after a recent assignment.
        # Keep local count to prevent re-assigning over capacity.
        effective_count = local_count
        Agent.objects.filter(pk=agent.pk).update(
            sat_last_count_sync_at=now,
            updated_at=now,
        )
        logger.debug(
            "sat_reconcile_keeping_local_count",
            agent=agent.name,
            local_count=local_count,
            hubspot_count=hubspot_count,
            hint="HubSpot count likely lagging recent assignment; hourly reconcile will correct if needed",
        )
    else:
        # Counts match — just update sync timestamp
        effective_count = hubspot_count
        Agent.objects.filter(pk=agent.pk).update(
            sat_last_count_sync_at=now,
            updated_at=now,
        )

    agent.sat_last_count_sync_at = now
    return effective_count


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
        Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True))
        .exclude(hubspot_owner_id__isnull=True)
        .only(
            "id",
            "name",
            "status_enum",
            "last_status_change_at",
            "online_time_seconds_today",
            "away_time_seconds_today",
        )
    )

    # Collect daily log snapshots for bulk upsert
    daily_log_snapshots: list[tuple[Agent, int, int]] = []

    for agent in agents:
        # Flush any pending time for the current status before reset
        if agent.last_status_change_at and agent.status_enum in ("online", "away", "busy"):
            delta_seconds = int((now - agent.last_status_change_at).total_seconds())
            if delta_seconds > 0:
                if agent.status_enum == "online":
                    agent.online_time_seconds_today += delta_seconds
                else:
                    agent.away_time_seconds_today += delta_seconds

        # Collect snapshot data for batch upsert
        if agent.online_time_seconds_today > 0 or agent.away_time_seconds_today > 0:
            daily_log_snapshots.append((agent, agent.online_time_seconds_today, agent.away_time_seconds_today))

        # Reset counters and anchor time
        agent.online_time_seconds_today = 0
        agent.away_time_seconds_today = 0
        agent.last_status_change_at = now

    # Batch upsert daily log snapshots
    for agent_ref, online_s, away_s in daily_log_snapshots:
        AgentDailyTimeLog.objects.update_or_create(
            agent=agent_ref,
            log_date=yesterday,
            defaults={
                "online_time_seconds": online_s,
                "away_time_seconds": away_s,
            },
        )

    # Bulk update all agents in one query instead of N individual saves
    if agents:
        Agent.objects.bulk_update(
            agents,
            ["online_time_seconds_today", "away_time_seconds_today", "last_status_change_at"],
            batch_size=50,
        )

    logger.info("sat_daily_counters_reset", agents_reset=len(agents), snapshot_date=str(yesterday))
    return {"agents_reset": len(agents)}
