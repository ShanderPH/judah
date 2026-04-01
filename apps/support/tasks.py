"""Celery tasks for the support / auto-assignment system."""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.db.models import Avg, Count, Max, Min
from django.utils import timezone

from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30, name="support.task_process_new_ticket_event")
def task_process_new_ticket_event(self, hubspot_ticket_id: str, entered_at_ms: str | None = None) -> bool:
    """Celery task: validate and auto-assign a new HubSpot ticket.

    Retries up to 3 times on transient failures (e.g., HubSpot API rate-limit).

    Args:
        hubspot_ticket_id: HubSpot ticket ID string.
        entered_at_ms: Value of ``hs_v2_date_entered_939275049`` (ms epoch).

    Returns:
        True if assignment succeeded, False otherwise.
    """
    from apps.support.auto_assign_service import process_new_ticket_event

    try:
        result = process_new_ticket_event(hubspot_ticket_id, entered_at_ms)
        logger.info(
            "task_process_new_ticket_done",
            ticket_id=hubspot_ticket_id,
            assigned=result,
        )
        return result
    except Exception as exc:
        logger.warning(
            "task_process_new_ticket_retry",
            ticket_id=hubspot_ticket_id,
            error=str(exc),
            retry=self.request.retries,
        )
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=30, name="support.task_handle_ticket_closed")
def task_handle_ticket_closed(
    self,
    hubspot_ticket_id: str,
    closed_at_ms: str | None = None,
    owner_id: str | None = None,
) -> None:
    """Celery task: record ticket closure and compute handle time.

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

    # Percentile calculation (p50, p95) via raw SQL for portability
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
    Does NOT perform any assignment — tickets will be picked up automatically
    once an eligible agent comes online.

    Designed to run daily at 08:00 (America/Sao_Paulo) and also callable
    on-demand via the ``POST /api/v1/support/queue/sync-novo/`` endpoint.

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


@shared_task(name="support.task_poll_hubspot_agent_status")
def task_poll_hubspot_agent_status() -> dict:
    """Celery task: sync agent availability from HubSpot Users API.

    Polls ``GET /settings/v3/users`` every few minutes and updates
    ``agents.status_enum`` in the local DB so the assignment queue
    always reflects real HubSpot availability.

    Mapping:
      ``hs_availability_status = "available"`` → ``status_enum = "online"``
      ``hs_availability_status = "away"`` (or any other)  → ``status_enum = "away"``

    Returns:
        Dict with ``updated``, ``skipped``, ``not_found`` counts.
    """
    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.support.models import Agent

    client = get_hubspot_client()
    users = client.get_all_owners_availability()

    updated = 0
    skipped = 0
    not_found = 0

    # Build a lookup: email → status_enum (emails are unique across HubSpot users)
    for user in users:
        email = (user.get("email") or "").lower().strip()
        new_status = user["status_enum"]

        if not email:
            skipped += 1
            continue

        try:
            agent = Agent.objects.filter(agent_email__iexact=email).exclude(is_active=False).get()
        except Agent.DoesNotExist:
            not_found += 1
            continue
        except Agent.MultipleObjectsReturned:
            logger.warning("agent_email_duplicate", email=email)
            skipped += 1
            continue

        if agent.status_enum != new_status:
            old_status = agent.status_enum
            agent.status_enum = new_status
            agent.updated_at = timezone.now()
            agent.save(update_fields=["status_enum", "updated_at"])
            logger.info(
                "agent_status_synced",
                agent=agent.name,
                email=email,
                old_status=old_status,
                new_status=new_status,
            )
            updated += 1
        else:
            skipped += 1

    logger.info(
        "task_poll_hubspot_agent_status_done",
        updated=updated,
        skipped=skipped,
        not_found=not_found,
    )

    # If any agent just came online, attempt to drain the pending queue so
    # tickets that arrived while no agent was available are assigned promptly.
    if updated > 0 and Agent.objects.filter(status_enum="online").exclude(is_active=False).exists():
        from apps.support.auto_assign_service import assign_pending_tickets

        assign_result = assign_pending_tickets()
        logger.info("task_poll_pending_assignment_triggered", **assign_result)

    return {"updated": updated, "skipped": skipped, "not_found": not_found}


@shared_task(name="support.task_aggregate_agent_metrics")
def task_aggregate_agent_metrics() -> dict:
    """Celery task: compute and persist per-agent metrics from closed conversations.

    Aggregates data from ``closed_conversations`` and ``assignment_logs`` for
    each active agent and upserts a row in ``agent_metrics``.

    Should run daily (e.g., at 00:10 AM) after ``task_aggregate_queue_metrics``.

    Returns:
        Dict with ``updated`` and ``skipped`` counts.
    """
    from apps.support.models import Agent, AgentMetrics, AssignmentLog, ClosedConversation

    agents = list(Agent.objects.exclude(is_active=False))
    now = timezone.now()
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

        _, upserted = AgentMetrics.objects.update_or_create(
            agent_id=agent.hubspot_owner_id,
            defaults={
                "total_chats": total_chats + total_auto,
                "chats_closed": total_chats,
                "average_ticket_time_min": avg_handle,
                "average_response_time_min": avg_wait_min,
                "last_time_updated": now,
            },
        )
        if upserted:
            updated += 1
        else:
            skipped += 1

    logger.info("task_aggregate_agent_metrics_done", updated=updated, skipped=skipped)
    return {"updated": updated, "skipped": skipped}
