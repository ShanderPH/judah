"""Celery tasks for the support / auto-assignment system.

Tasks are organized into three groups:

**SAT (Smart Agent Tracking):**
  - ``task_sat_heartbeat`` — 20-second status sync heartbeat
  - ``task_sat_reset_daily_counters`` — midnight daily counter snapshot

**Matchmaker (Async Assignment):**
  - ``task_matchmaker_assign_single`` — enqueue + assign a single ticket
  - ``task_matchmaker_drain_queue`` — drain all pending tickets

**Lifecycle:**
  - ``task_handle_ticket_closed`` — record closure and compute handle time
  - ``task_handle_owner_change`` — process ticket owner reassignment
  - ``task_handle_availability_change`` — process agent availability webhook

**Aggregation (unchanged):**
  - ``task_sync_hubspot_team_members`` — daily team sync
  - ``task_aggregate_queue_metrics`` — daily queue metrics
  - ``task_sync_novo_stage_tickets`` — daily NOVO-stage backfill
  - ``task_aggregate_agent_metrics`` — daily per-agent metrics
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.db.models import Avg, Count, Max, Min
from django.utils import timezone

from celery import shared_task

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# SAT tasks
# ---------------------------------------------------------------------------


@shared_task(name="support.task_sat_heartbeat")
def task_sat_heartbeat() -> dict:
    """SAT heartbeat — sync agent availability from HubSpot every 20 seconds.

    Skips execution during off-hours (returns immediately with no API calls).
    When agents transition to ONLINE, dispatches Matchmaker drain.
    """
    from apps.support.sat_service import sat_heartbeat

    return sat_heartbeat()


@shared_task(name="support.task_sat_reset_daily_counters")
def task_sat_reset_daily_counters() -> dict:
    """SAT daily reset — snapshot time counters and reset to zero.

    Should run at 00:01 AM (America/Sao_Paulo).
    """
    from apps.support.sat_service import sat_reset_daily_counters

    result = sat_reset_daily_counters()
    logger.info("task_sat_reset_daily_counters_done", **result)
    return result


# ---------------------------------------------------------------------------
# Matchmaker tasks
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="support.task_matchmaker_assign_single",
)
def task_matchmaker_assign_single(
    self,
    hubspot_ticket_id: str,
    entered_at_ms: str | None = None,
) -> bool:
    """Enqueue a ticket and attempt immediate assignment.

    Called by the webhook handler when a ticket enters the NOVO stage.
    Uses a Redis dedup lock to prevent duplicate processing from webhook retries.

    Args:
        hubspot_ticket_id: HubSpot ticket ID.
        entered_at_ms: HubSpot millisecond timestamp.

    Returns:
        True if assigned, False otherwise.
    """
    from django.core.cache import cache

    from apps.support.matchmaker_service import enqueue_new_ticket, matchmaker_assign_next

    # Redis dedup lock — prevent duplicate processing from webhook retries
    lock_key = f"matchmaker_assign:{hubspot_ticket_id}"
    if not cache.add(lock_key, "1", timeout=30):
        logger.info(
            "task_matchmaker_assign_single_dedup",
            ticket_id=hubspot_ticket_id,
        )
        return False

    try:
        new_conv = enqueue_new_ticket(hubspot_ticket_id, entered_at_ms)
        if new_conv is None:
            return False

        result = matchmaker_assign_next()
        logger.info(
            "task_matchmaker_assign_single_done",
            ticket_id=hubspot_ticket_id,
            assigned=result,
        )
        return result
    except Exception as exc:
        logger.warning(
            "task_matchmaker_assign_single_retry",
            ticket_id=hubspot_ticket_id,
            error=str(exc),
            retry=self.request.retries,
        )
        raise self.retry(exc=exc) from exc


@shared_task(name="support.task_matchmaker_drain_queue")
def task_matchmaker_drain_queue() -> dict:
    """Drain all pending tickets from the queue.

    Triggered by:
      - SAT heartbeat when an agent comes online
      - Celery Beat safety net (every 60 seconds)

    Uses a Redis lock to prevent overlapping drains.
    """
    from django.core.cache import cache

    from apps.support.agent_sync_service import is_business_hours
    from apps.support.matchmaker_service import matchmaker_drain_queue

    if not is_business_hours():
        return {"skipped_off_hours": True}

    # Redis lock — prevent overlapping drains
    lock_key = "matchmaker_drain_lock"
    if not cache.add(lock_key, "1", timeout=60):
        logger.debug("task_matchmaker_drain_queue_locked")
        return {"skipped_locked": True}

    try:
        result = matchmaker_drain_queue()
        logger.info("task_matchmaker_drain_queue_done", **result)
        return result
    finally:
        cache.delete(lock_key)


# ---------------------------------------------------------------------------
# Lifecycle tasks (async webhook handlers)
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=3, default_retry_delay=30, name="support.task_handle_ticket_closed")
def task_handle_ticket_closed(
    self,
    hubspot_ticket_id: str,
    closed_at_ms: str | None = None,
    owner_id: str | None = None,
) -> None:
    """Record ticket closure and compute handle time.

    Args:
        hubspot_ticket_id: HubSpot ticket ID string.
        closed_at_ms: Value of ``hs_v2_date_entered_939275052`` (ms epoch).
        owner_id: HubSpot owner ID at the time of closure.
    """
    from apps.support.auto_assign_service import handle_ticket_closed

    try:
        handle_ticket_closed(hubspot_ticket_id, closed_at_ms, owner_id)
    except Exception as exc:
        logger.warning(
            "task_handle_ticket_closed_retry",
            ticket_id=hubspot_ticket_id,
            error=str(exc),
        )
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=15, name="support.task_handle_owner_change")
def task_handle_owner_change(
    self,
    hubspot_ticket_id: str,
    new_owner_id: str | None,
    payload: dict,
) -> None:
    """Process ticket owner reassignment asynchronously.

    Handles chat count adjustments, AssignedConversation updates, and
    ConversationReassignment logging.

    Args:
        hubspot_ticket_id: HubSpot ticket ID.
        new_owner_id: New hubspot_owner_id value.
        payload: Full webhook payload containing previousValue.
    """
    from decimal import Decimal

    from django.db import transaction

    from apps.support.models import Agent, AssignedConversation, ConversationReassignment
    from apps.support.queue_service import decrement_agent_chat_count, increment_agent_chat_count

    try:
        previous_owner_id = payload.get("previousValue") or payload.get("sourceId")
        new_owner = new_owner_id.strip() if new_owner_id else ""
        prev_owner = str(previous_owner_id).strip() if previous_owner_id else ""

        # Skip if no actual change or initial assignment
        if not prev_owner or prev_owner in ("", "None", "null"):
            return
        if new_owner == prev_owner:
            return

        logger.info(
            "task_owner_change_processing",
            ticket_id=hubspot_ticket_id,
            from_owner_id=prev_owner,
            to_owner_id=new_owner,
        )

        now = timezone.now()

        # Resolve agents
        import contextlib

        from_agent: Agent | None = None
        to_agent: Agent | None = None

        with contextlib.suppress(ValueError, TypeError):
            from_agent = Agent.objects.filter(hubspot_owner_id=int(prev_owner)).first()

        if new_owner and new_owner not in ("", "None", "null"):
            with contextlib.suppress(ValueError, TypeError):
                to_agent = Agent.objects.filter(hubspot_owner_id=int(new_owner)).first()

        # Calculate time with previous agent
        time_with_prev_seconds: Decimal | None = None
        assigned_conv = AssignedConversation.objects.filter(hubspot_ticket_id=hubspot_ticket_id).first()

        if assigned_conv and assigned_conv.assigned_at:
            delta = now - assigned_conv.assigned_at
            time_with_prev_seconds = Decimal(str(round(delta.total_seconds(), 2)))

        with transaction.atomic():
            if from_agent:
                decrement_agent_chat_count(from_agent)

            if to_agent:
                increment_agent_chat_count(to_agent)

            if assigned_conv:
                if to_agent:
                    assigned_conv.agent = to_agent
                    assigned_conv.hubspot_owner_id = to_agent.hubspot_owner_id
                    assigned_conv.agent_name = to_agent.name
                    assigned_conv.assignment_count += 1
                else:
                    assigned_conv.agent = None
                    assigned_conv.hubspot_owner_id = int(new_owner) if new_owner else None
                    assigned_conv.agent_name = ""
                assigned_conv.save(
                    update_fields=["agent", "hubspot_owner_id", "agent_name", "assignment_count", "updated_at"]
                )

            ConversationReassignment.objects.create(
                hubspot_ticket_id=hubspot_ticket_id,
                from_agent=from_agent,
                from_hubspot_owner_id=int(prev_owner) if prev_owner else None,
                from_agent_name=from_agent.name if from_agent else None,
                to_agent=to_agent,
                to_hubspot_owner_id=int(new_owner) if new_owner else None,
                to_agent_name=to_agent.name if to_agent else None,
                reassigned_at=now,
                time_with_previous_agent_seconds=time_with_prev_seconds,
                reassignment_source="hubspot_webhook",
            )

        logger.info(
            "task_owner_change_done",
            ticket_id=hubspot_ticket_id,
            from_agent=from_agent.name if from_agent else prev_owner,
            to_agent=to_agent.name if to_agent else new_owner,
        )
    except Exception as exc:
        logger.warning(
            "task_handle_owner_change_retry",
            ticket_id=hubspot_ticket_id,
            error=str(exc),
        )
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=15, name="support.task_handle_availability_change")
def task_handle_availability_change(
    self,
    hubspot_contact_id: str,
    availability_value: str,
    payload: dict,
) -> None:
    """Process agent availability change from webhook asynchronously.

    Resolves agent email from contact ID, updates status, and dispatches
    Matchmaker drain if agent came online.

    Args:
        hubspot_contact_id: HubSpot contact ID.
        availability_value: HubSpot availability status string.
        payload: Full webhook payload.
    """
    try:
        new_status = "online" if availability_value == "available" else "away"

        # Try to get email from payload first
        email = (payload.get("email") or "").lower().strip()

        if not email:
            from apps.integrations.hubspot.client import get_hubspot_client

            client = get_hubspot_client()
            contact_details = client.get_contact_by_id(hubspot_contact_id)
            email = (contact_details.get("email") or "").lower().strip()

        if not email:
            logger.warning(
                "task_availability_change_no_email",
                contact_id=hubspot_contact_id,
            )
            return

        from apps.support.models import Agent, AgentStatusHistory

        agent = Agent.objects.filter(agent_email__iexact=email).exclude(is_active=False).first()
        if agent is None:
            logger.debug("task_availability_change_agent_not_found", email=email)
            return

        old_status = agent.status_enum
        if old_status == new_status:
            return

        now = timezone.now()

        # Accumulate time before switching
        from apps.support.sat_service import sat_accumulate_time

        sat_accumulate_time(agent, old_status, new_status, now)

        agent.status_enum = new_status
        agent.last_status_change_at = now
        agent.updated_at = now
        agent.save(
            update_fields=[
                "status_enum",
                "last_status_change_at",
                "online_time_seconds_today",
                "away_time_seconds_today",
                "updated_at",
            ]
        )

        AgentStatusHistory.objects.create(
            agent=agent,
            old_status=old_status,
            new_status=new_status,
            sync_source="hubspot_webhook",
        )

        logger.info(
            "task_availability_change_done",
            agent=agent.name,
            old_status=old_status,
            new_status=new_status,
        )

        # If agent came online, trigger Matchmaker
        if new_status == "online":
            task_matchmaker_drain_queue.delay()

    except Exception as exc:
        logger.warning(
            "task_handle_availability_change_retry",
            contact_id=hubspot_contact_id,
            error=str(exc),
        )
        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Aggregation / sync tasks (unchanged logic, retained for compatibility)
# ---------------------------------------------------------------------------


@shared_task(name="support.task_sync_hubspot_team_members")
def task_sync_hubspot_team_members() -> int:
    """Celery task: sync HubSpot N1 team members into the agents table.

    Designed to run periodically (e.g., daily) so newly-added team members
    are automatically registered in the queue system.

    Returns:
        Number of new agents created.
    """
    from django.conf import settings

    from apps.support.auto_assign_service import sync_hubspot_team_to_agents

    team_id = getattr(settings, "HUBSPOT_N1_TEAM_ID", "8")
    created = sync_hubspot_team_to_agents(team_id)
    logger.info("task_sync_hubspot_team_done", team_id=team_id, created=created)
    return created


@shared_task(name="support.task_aggregate_queue_metrics")
def task_aggregate_queue_metrics() -> None:
    """Celery task: compute and persist daily queue performance metrics.

    Should run once daily (e.g., at 00:05 AM) to aggregate the previous day.
    """
    from apps.support.models import AssignedConversation, NewConversation, QueuePerformanceMetrics

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    entered = NewConversation.objects.filter(entered_queue_at__date=yesterday).count()

    assigned_qs = AssignedConversation.objects.filter(assigned_at__date=yesterday)
    assigned_count = assigned_qs.count()

    closed_qs = AssignedConversation.objects.filter(closed_at__date=yesterday)
    closed_count = closed_qs.count()

    # Queue wait time aggregates
    wait_agg = assigned_qs.filter(queue_wait_seconds__isnull=False).aggregate(
        avg=Avg("queue_wait_seconds"),
        min=Min("queue_wait_seconds"),
        max=Max("queue_wait_seconds"),
    )

    # Percentile calculation (p50, p95)
    p50: float | None = None
    p95: float | None = None
    wait_values = list(
        assigned_qs.filter(queue_wait_seconds__isnull=False)
        .order_by("queue_wait_seconds")
        .values_list("queue_wait_seconds", flat=True)
    )
    if wait_values:
        n = len(wait_values)
        p50_idx = int(n * 0.50)
        p95_idx = min(int(n * 0.95), n - 1)
        p50 = float(wait_values[p50_idx])
        p95 = float(wait_values[p95_idx])

    # Handle time aggregate
    handle_agg = closed_qs.filter(total_handle_time_minutes__isnull=False).aggregate(
        avg=Avg("total_handle_time_minutes")
    )

    # Breakdown by agent
    assignments_by_agent: dict[str, int] = {}
    for row in assigned_qs.values("hubspot_owner_id").annotate(cnt=Count("id")):
        assignments_by_agent[str(row["hubspot_owner_id"])] = row["cnt"]

    QueuePerformanceMetrics.objects.update_or_create(
        metric_date=yesterday,
        defaults={
            "total_entered_queue": entered,
            "total_assigned": assigned_count,
            "total_closed": closed_count,
            "avg_queue_wait_seconds": wait_agg.get("avg"),
            "min_queue_wait_seconds": wait_agg.get("min"),
            "max_queue_wait_seconds": wait_agg.get("max"),
            "p50_queue_wait_seconds": p50,
            "p95_queue_wait_seconds": p95,
            "avg_handle_time_minutes": handle_agg.get("avg"),
            "assignments_by_agent": assignments_by_agent,
        },
    )

    logger.info(
        "task_aggregate_queue_metrics_done",
        date=str(yesterday),
        assigned=assigned_count,
        closed=closed_count,
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="support.task_sync_novo_stage_tickets")
def task_sync_novo_stage_tickets(self) -> dict:
    """Celery task: sync HubSpot NOVO-stage tickets into the internal queue.

    Fetches all tickets currently in stage ``939275049`` (NOVO) from HubSpot
    and creates ``NewConversation`` records for those not yet tracked locally.
    After populating, triggers Matchmaker drain.

    Returns:
        Dict with ``created``, ``skipped``, ``total_from_hubspot`` counts.
    """
    from apps.support.auto_assign_service import sync_novo_stage_tickets

    try:
        result = sync_novo_stage_tickets()
        logger.info("task_sync_novo_stage_tickets_done", **result)
        return result
    except Exception as exc:
        logger.warning("task_sync_novo_stage_tickets_retry", error=str(exc), retry=self.request.retries)
        raise self.retry(exc=exc) from exc


@shared_task(name="support.task_aggregate_agent_metrics")
def task_aggregate_agent_metrics() -> dict:
    """Celery task: compute and persist per-agent metrics.

    Aggregates data from closed conversations, assignment logs, and daily
    time logs for each active agent.

    Should run daily (e.g., at 00:10 AM) after ``task_aggregate_queue_metrics``.

    Returns:
        Dict with ``updated`` and ``skipped`` counts.
    """
    from apps.support.models import Agent, AgentDailyTimeLog, AgentMetrics, AssignmentLog, ClosedConversation

    agents = list(Agent.objects.exclude(is_active=False))
    now = timezone.now()
    yesterday = timezone.localdate() - timedelta(days=1)
    updated = 0
    skipped = 0

    for agent in agents:
        closed_qs = ClosedConversation.objects.filter(agent=agent)
        total_chats = closed_qs.count()

        handle_agg = closed_qs.filter(total_handle_time_minutes__isnull=False).aggregate(
            avg=Avg("total_handle_time_minutes"),
        )
        avg_handle = float(handle_agg.get("avg") or 0.0)

        wait_agg = closed_qs.filter(queue_wait_seconds__isnull=False).aggregate(
            avg=Avg("queue_wait_seconds"),
        )
        avg_wait_min = float(wait_agg.get("avg") or 0.0) / 60.0

        total_auto = AssignmentLog.objects.filter(
            agent=agent,
            assignment_type="automatic",
        ).count()

        # Compute average online/away time from daily logs (last 30 days)
        time_logs = AgentDailyTimeLog.objects.filter(
            agent=agent,
            log_date__gte=yesterday - timedelta(days=30),
        )
        avg_online = 0.0
        avg_away = 0.0
        if time_logs.exists():
            time_agg = time_logs.aggregate(
                avg_online=Avg("online_time_seconds"),
                avg_away=Avg("away_time_seconds"),
            )
            avg_online = float(time_agg.get("avg_online") or 0.0)
            avg_away = float(time_agg.get("avg_away") or 0.0)

        _, upserted = AgentMetrics.objects.update_or_create(
            agent_id=agent.hubspot_owner_id,
            defaults={
                "total_chats": total_chats + total_auto,
                "chats_closed": total_chats,
                "average_ticket_time_min": avg_handle,
                "average_response_time_min": avg_wait_min,
                "average_online_time": avg_online,
                "average_away_time": avg_away,
                "last_time_updated": now,
            },
        )
        if upserted:
            updated += 1
        else:
            skipped += 1

    logger.info("task_aggregate_agent_metrics_done", updated=updated, skipped=skipped)
    return {"updated": updated, "skipped": skipped}
