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

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.support.agent_sync_service import is_business_hours

if TYPE_CHECKING:
    from apps.support.eligibility_service import EligibilityDecision

logger = structlog.get_logger(__name__)


def _acquire_reconciliation_lease() -> tuple[str, int] | None:
    """Acquire the singleton database lease and return its token/generation."""
    from apps.support.availability_runtime import availability_writer_id, runtime_environment
    from apps.support.models import AvailabilityReconciliationLease

    now = timezone.now()
    token = uuid.uuid4().hex
    writer_id = availability_writer_id()
    lease_ttl = timedelta(seconds=int(settings.AVAILABILITY_LEASE_TTL_SECONDS))
    with transaction.atomic():
        lease, _ = AvailabilityReconciliationLease.objects.select_for_update().get_or_create(
            key="sat-authoritative-reconciliation"
        )
        if lease.expires_at and lease.expires_at > now and lease.owner_token:
            logger.warning(
                "sat_lease_contended",
                owner_writer_id=lease.writer_id,
                contender_writer_id=writer_id,
                generation=lease.generation,
            )
            return None
        lease.owner_token = token
        lease.writer_id = writer_id
        lease.runtime_environment = runtime_environment()
        lease.expires_at = now + lease_ttl
        lease.generation += 1
        lease.save()
        return token, lease.generation


def _release_reconciliation_lease(token: str) -> bool:
    """Release the singleton lease only when this task still owns it."""
    from apps.support.models import AvailabilityReconciliationLease

    with transaction.atomic():
        lease = (
            AvailabilityReconciliationLease.objects.select_for_update()
            .filter(key="sat-authoritative-reconciliation")
            .first()
        )
        if lease is None or lease.owner_token != token:
            return False
        lease.owner_token = ""
        lease.expires_at = None
        lease.save(update_fields=["owner_token", "expires_at", "updated_at"])
        return True


def _raw_state_hash(item: dict[str, Any]) -> str:
    """Return a deterministic redacted hash for an invalid observation."""
    state = {
        "user_id": item.get("user_id"),
        "availability_status": item.get("availability_status"),
        "out_of_office_hours": item.get("out_of_office_hours"),
        "working_hours": item.get("working_hours"),
        "timezone": item.get("timezone"),
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


def _legacy_sat_heartbeat() -> dict:
    """Compatibility alias that cannot bypass authoritative reconciliation."""
    return sat_heartbeat()

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


def sat_heartbeat(task_id: str = "", *, force_refresh: bool = False) -> dict:
    """Reconcile authoritative HubSpot availability into fail-closed state.

    Args:
        task_id: Celery task identifier used for audit events.
        force_refresh: Bypass the HubSpot availability cache. Ticket-triggered
            reconciliation uses this before attempting an assignment.
    """
    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.integrations.hubspot.user_availability import (
        AvailabilityParseError,
        normalize_availability_item,
    )
    from apps.support.availability_runtime import (
        availability_writer_id,
        is_authoritative_availability_runtime,
        log_runtime_rejection,
        runtime_environment,
    )
    from apps.support.eligibility_service import (
        EligibilityDecision,
        EligibilityReason,
        evaluate_observation_signals,
    )
    from apps.support.models import (
        Agent,
        AgentAvailabilityDecision,
        AgentStatusHistory,
    )

    if not is_authoritative_availability_runtime():
        log_runtime_rejection("sat_heartbeat")
        return {
            "agents_checked": 0,
            "status_changes": 0,
            "agents_came_online": 0,
            "skipped_non_authoritative_runtime": True,
        }
    if not is_business_hours():
        return {
            "agents_checked": 0,
            "status_changes": 0,
            "agents_came_online": 0,
            "skipped_off_hours": True,
        }

    lease = _acquire_reconciliation_lease()
    if lease is None:
        return {
            "agents_checked": 0,
            "status_changes": 0,
            "agents_came_online": 0,
            "skipped_locked": True,
        }
    lease_token, fencing_token = lease

    try:
        availability_data = get_hubspot_client().get_all_owners_availability(force_refresh=force_refresh)
    except Exception as exc:
        logger.warning("sat_heartbeat_availability_fetch_failed", error=str(exc))
        _release_reconciliation_lease(lease_token)
        return {
            "agents_checked": 0,
            "status_changes": 0,
            "agents_came_online": 0,
            "error": str(exc),
        }

    now = timezone.now()
    writer_id = availability_writer_id()
    environment = runtime_environment()
    strict_evaluation = bool(settings.ABSENCE_SAFE_ELIGIBILITY_SHADOW or settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED)
    by_user_id = {str(item.get("user_id") or ""): item for item in availability_data if item.get("user_id")}
    by_email: dict[str, list[dict[str, Any]]] = {}
    for item in availability_data:
        email = str(item.get("email") or "").strip().lower()
        if email:
            by_email.setdefault(email, []).append(item)

    status_changes = 0
    agents_came_online = 0
    agents_checked = 0

    try:
        with transaction.atomic():
            agents = list(
                Agent.objects.select_for_update()
                .filter(Q(is_active=True) | Q(is_active__isnull=True))
                .exclude(hubspot_owner_id__isnull=True)
                .order_by("id")
            )
            for agent in agents:
                if agent.availability_fencing_token > fencing_token:
                    logger.warning(
                        "availability_writer_conflict",
                        agent_id=str(agent.id),
                        stale_fencing_token=fencing_token,
                        current_fencing_token=agent.availability_fencing_token,
                    )
                    continue

                agents_checked += 1
                email = (agent.agent_email or "").strip().lower()
                item = by_user_id.get(agent.hubspot_user_id or "")
                if item is None and len(by_email.get(email, [])) == 1:
                    item = by_email[email][0]

                old_status = agent.status_enum
                old_eligibility = agent.eligibility_state
                raw_hash = _raw_state_hash(item or {})
                remote_status = ""
                decision = EligibilityDecision(False, EligibilityReason.MISSING_OBSERVATION)
                online_since = None
                sample_count = 0
                observation = None

                if item is not None:
                    if not strict_evaluation:
                        item = {
                            **item,
                            "user_id": item.get("user_id") or f"legacy:{email}",
                            "availability_status": item.get("availability_status")
                            or ("available" if item.get("status_enum") == "online" else "away"),
                            "working_hours": item.get("working_hours")
                            or '[{"days":"EVERY_DAY","startMinute":0,"endMinute":1440}]',
                            "timezone": item.get("timezone") or "UTC",
                        }
                    remote_status = str(item.get("availability_status") or "").strip().lower()
                    try:
                        observation = normalize_availability_item(item, now)
                        raw_hash = observation.raw_state_hash
                        decision = evaluate_observation_signals(observation, now)
                    except AvailabilityParseError:
                        decision = EligibilityDecision(False, EligibilityReason.MALFORMED_REMOTE_DATA)

                if agent.is_active is False:
                    decision = EligibilityDecision(False, EligibilityReason.AGENT_INACTIVE)
                elif not agent.auto_assign_enabled:
                    decision = EligibilityDecision(False, EligibilityReason.AUTO_ASSIGN_DISABLED)

                if decision.eligible and strict_evaluation:
                    if agent.remote_availability_status == "available" and agent.availability_online_since:
                        online_since = agent.availability_online_since
                        sample_count = agent.availability_sample_count + 1
                    else:
                        online_since = now
                        sample_count = 1
                    stable_seconds = (now - online_since).total_seconds()
                    required_samples = int(settings.AVAILABILITY_REQUIRED_SAMPLES)
                    required_seconds = int(settings.AVAILABILITY_STABLE_SECONDS)
                    if sample_count < required_samples or stable_seconds < required_seconds:
                        decision = EligibilityDecision(False, EligibilityReason.STABILIZING)
                elif decision.eligible:
                    online_since = now
                    sample_count = 1

                if settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED:
                    new_status = Agent.StatusEnum.ONLINE if decision.eligible else Agent.StatusEnum.AWAY
                else:
                    new_status = Agent.StatusEnum.ONLINE if remote_status == "available" else Agent.StatusEnum.AWAY
                agent.availability_revision += 1
                agent.availability_fencing_token = fencing_token
                agent.availability_writer_id = writer_id
                agent.availability_observed_at = now
                agent.availability_online_since = online_since
                agent.availability_sample_count = sample_count
                agent.remote_availability_status = remote_status
                agent.eligibility_state = decision.state
                agent.eligibility_reason = decision.reason.value
                agent.eligibility_evaluated_at = now
                agent.sat_last_heartbeat_at = now
                agent.updated_at = now

                if observation is not None:
                    agent.hubspot_user_id = observation.hubspot_user_id
                    agent.remote_out_of_office_hours = [
                        value.model_dump(mode="json", by_alias=True) for value in observation.out_of_office_hours
                    ]
                    agent.remote_working_hours = [
                        value.model_dump(mode="json", by_alias=True) for value in observation.working_hours
                    ]
                    agent.remote_timezone = observation.timezone_name

                if old_status != new_status:
                    sat_accumulate_time(agent, old_status, new_status, now)
                    agent.status_enum = new_status
                    agent.last_status_change_at = now
                    status_changes += 1
                    AgentStatusHistory.objects.create(
                        agent=agent,
                        old_status=old_status,
                        new_status=new_status,
                        sync_source=("hubspot_users_reconciliation" if strict_evaluation else "sat_heartbeat"),
                        metadata={
                            "task_id": task_id,
                            "writer_id": writer_id,
                            "runtime_environment": environment,
                            "raw_state_hash": raw_hash,
                            "eligibility_reason": decision.reason.value,
                            "fencing_token": fencing_token,
                        },
                    )

                if (
                    settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED and old_eligibility != "eligible" and decision.eligible
                ) or (
                    not settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED
                    and old_status != Agent.StatusEnum.ONLINE
                    and new_status == Agent.StatusEnum.ONLINE
                ):
                    agents_came_online += 1

                agent.save()
                AgentAvailabilityDecision.objects.create(
                    agent=agent,
                    revision=agent.availability_revision,
                    old_status=old_status,
                    new_status=new_status,
                    remote_status=remote_status,
                    raw_state_hash=raw_hash,
                    observed_at=now,
                    eligibility_state=decision.state,
                    eligibility_reason=decision.reason.value,
                    task_id=task_id,
                    writer_id=writer_id,
                    runtime_environment=environment,
                    fencing_token=fencing_token,
                )

            if agents_came_online:
                from apps.support.tasks import task_matchmaker_drain_queue

                transaction.on_commit(task_matchmaker_drain_queue.delay)
    finally:
        if not _release_reconciliation_lease(lease_token):
            logger.warning(
                "sat_lease_release_rejected",
                writer_id=writer_id,
                fencing_token=fencing_token,
            )

    logger.info(
        "sat_heartbeat_done",
        agents_checked=agents_checked,
        status_changes=status_changes,
        agents_came_online=agents_came_online,
        writer_id=writer_id,
        fencing_token=fencing_token,
    )
    return {
        "agents_checked": agents_checked,
        "status_changes": status_changes,
        "agents_came_online": agents_came_online,
        "skipped_off_hours": False,
        "fencing_token": fencing_token,
    }


def sat_verify_agent_assignment_eligibility(agent) -> EligibilityDecision:
    """Read one HubSpot user immediately before assignment and fail closed.

    This verification is intentionally read-only and deterministic: repeated
    calls with the same HubSpot response produce the same decision without
    mutating the persisted SAT snapshot or its revision.
    """
    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.integrations.hubspot.user_availability import (
        AvailabilityParseError,
        normalize_availability_item,
    )
    from apps.support.eligibility_service import (
        EligibilityDecision,
        EligibilityReason,
        evaluate_observation_signals,
    )

    user_id = str(agent.hubspot_user_id or "").strip()
    if not user_id:
        return EligibilityDecision(False, EligibilityReason.MISSING_IDENTITY)

    remote = get_hubspot_client().get_user_by_id(user_id)
    if not remote:
        return EligibilityDecision(False, EligibilityReason.MISSING_OBSERVATION)

    item = {
        "user_id": remote.get("id"),
        "email": remote.get("email"),
        "availability_status": remote.get("hs_availability_status"),
        "out_of_office_hours": remote.get("hs_out_of_office_hours"),
        "working_hours": remote.get("hs_working_hours"),
        "timezone": remote.get("hs_standard_time_zone"),
    }
    try:
        observation = normalize_availability_item(item, timezone.now())
    except AvailabilityParseError:
        return EligibilityDecision(False, EligibilityReason.MALFORMED_REMOTE_DATA)
    return evaluate_observation_signals(observation, timezone.now())


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
    from apps.support.availability_runtime import (
        log_runtime_rejection,
        may_write_routing_state,
    )
    from apps.support.models import Agent

    if not may_write_routing_state():
        log_runtime_rejection("sat_reconcile_agent_load")
        return agent.current_simultaneous_chats

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
    from apps.support.availability_runtime import (
        log_runtime_rejection,
        may_write_routing_state,
    )
    from apps.support.models import Agent, AgentDailyTimeLog

    if not may_write_routing_state():
        log_runtime_rejection("sat_reset_daily_counters")
        return {"agents_reset": 0, "skipped_non_authoritative_runtime": True}

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
