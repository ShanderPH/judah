"""Durable reserve/apply/finalize protocol for ticket owner assignments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.integrations.hubspot.client import get_hubspot_client
from apps.integrations.hubspot.exceptions import (
    HubSpotAPIError,
    HubSpotResourceNotFoundError,
)
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    NewConversation,
)

logger = structlog.get_logger(__name__)

LIVE_STATES = (
    AssignmentAttempt.State.RESERVED,
    AssignmentAttempt.State.EXTERNAL_APPLIED,
    AssignmentAttempt.State.COMPENSATING,
    AssignmentAttempt.State.RETRYABLE,
    AssignmentAttempt.State.REPAIR_REQUIRED,
)


@dataclass(frozen=True, slots=True)
class Reservation:
    """Result of a database reservation attempt."""

    attempt: AssignmentAttempt | None
    reason: str


def _database_now() -> datetime:
    """Return the transaction database clock."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_TIMESTAMP")
        value = cursor.fetchone()[0]
    if isinstance(value, str):
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    return value


def _ordered_candidates() -> list[Agent]:
    """Return all eligible candidates in the canonical fair order."""
    from apps.support.queue_service import get_last_assigned_owner_id, get_ranked_eligible_agents

    return get_ranked_eligible_agents(get_last_assigned_owner_id())


def _verify_candidates() -> list[tuple[Agent, str]]:
    """Perform authoritative provider vetoes outside database transactions."""
    from apps.support.eligibility_service import evaluate_persisted_agent
    from apps.support.sat_service import sat_verify_agent_assignment_eligibility

    candidates = _ordered_candidates()
    if not settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED:
        return [(agent, "legacy_rollout") for agent in candidates]

    verified: list[tuple[Agent, str]] = []
    captured_now = timezone.now()
    for agent in candidates:
        local = evaluate_persisted_agent(agent, captured_now)
        if not local.eligible:
            logger.info(
                "assignment_candidate_rejected",
                agent_id=str(agent.pk),
                reason=local.reason.value,
                source="persisted",
            )
            continue
        remote = sat_verify_agent_assignment_eligibility(agent, now=captured_now)
        if not remote.eligible:
            logger.info(
                "assignment_candidate_rejected",
                agent_id=str(agent.pk),
                reason=remote.reason.value,
                source="hubspot",
            )
            continue
        verified.append((agent, remote.reason.value))
    return verified


def reserve_next_assignment(ticket_id: str | None = None) -> Reservation:
    """Claim the oldest ready row and reserve one verified agent atomically."""
    from apps.support.eligibility_service import evaluate_persisted_agent

    now = timezone.now()
    ready = (
        NewConversation.objects.filter(
            automatic_assignment_eligible=True,
            queue_status__in=(
                NewConversation.QueueStatus.PENDING,
                NewConversation.QueueStatus.QUEUED,
            ),
        )
        .filter(Q(next_assignment_attempt_at__isnull=True) | Q(next_assignment_attempt_at__lte=now))
        .filter(Q(claim_expires_at__isnull=True) | Q(claim_expires_at__lte=now))
    )
    if ticket_id is not None:
        ready = ready.filter(hubspot_ticket_id=ticket_id)
        completed = AssignmentAttempt.objects.filter(
            ticket_id=ticket_id,
            state=AssignmentAttempt.State.COMPLETED,
        ).first()
        if completed is not None:
            return Reservation(completed, "completed")
    if not ready.exists():
        return Reservation(None, "queue_empty_or_claimed")

    candidates = _verify_candidates()
    if not candidates:
        _defer_without_candidate(ticket_id)
        return Reservation(None, "no_eligible_candidate")

    for candidate, reason in candidates:
        with transaction.atomic():
            database_now = _database_now()
            ready = (
                NewConversation.objects.filter(
                    automatic_assignment_eligible=True,
                    queue_status__in=(
                        NewConversation.QueueStatus.PENDING,
                        NewConversation.QueueStatus.QUEUED,
                    ),
                )
                .filter(Q(next_assignment_attempt_at__isnull=True) | Q(next_assignment_attempt_at__lte=database_now))
                .filter(Q(claim_expires_at__isnull=True) | Q(claim_expires_at__lte=database_now))
            )
            if ticket_id is not None:
                ready = ready.filter(hubspot_ticket_id=ticket_id)
            queue_row = ready.select_for_update(skip_locked=True).order_by("entered_queue_at", "id").first()
            if queue_row is None:
                completed = AssignmentAttempt.objects.filter(
                    ticket_id=ticket_id,
                    state=AssignmentAttempt.State.COMPLETED,
                ).first()
                return Reservation(completed, "completed" if completed else "queue_empty_or_claimed")

            existing = (
                AssignmentAttempt.objects.select_for_update()
                .filter(ticket_id=queue_row.hubspot_ticket_id, state__in=LIVE_STATES)
                .first()
            )
            if existing is not None:
                return Reservation(existing, "existing_attempt")

            locked_agent = Agent.objects.select_for_update().get(pk=candidate.pk)
            if locked_agent.availability_revision != candidate.availability_revision:
                logger.info(
                    "assignment_candidate_rejected",
                    agent_id=str(candidate.pk),
                    reason="eligibility_revision_changed",
                    source="database",
                )
                continue
            final_decision = evaluate_persisted_agent(locked_agent, database_now)
            eligible_now = (
                final_decision.eligible
                if settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED
                else locked_agent.current_simultaneous_chats < (locked_agent.max_simultaneous_chats or 5)
            )
            if not eligible_now:
                logger.info(
                    "assignment_candidate_rejected",
                    agent_id=str(candidate.pk),
                    reason=final_decision.reason.value,
                    source="database",
                )
                continue

            claim_token = uuid.uuid4().hex
            claim_ttl = int(getattr(settings, "ASSIGNMENT_CLAIM_TTL_SECONDS", 90))
            queue_row.claim_owner_token = claim_token
            queue_row.claimed_at = database_now
            queue_row.claim_expires_at = database_now + timedelta(seconds=claim_ttl)
            queue_row.assignment_attempts += 1
            queue_row.last_assignment_attempt_at = database_now
            queue_row.save(
                update_fields=[
                    "claim_owner_token",
                    "claimed_at",
                    "claim_expires_at",
                    "assignment_attempts",
                    "last_assignment_attempt_at",
                    "updated_at",
                ]
            )
            locked_agent.current_simultaneous_chats += 1
            locked_agent.last_assignment_at = database_now
            locked_agent.updated_at = database_now
            locked_agent.save(
                update_fields=[
                    "current_simultaneous_chats",
                    "last_assignment_at",
                    "updated_at",
                ]
            )
            attempt = AssignmentAttempt.objects.create(
                idempotency_key=uuid.uuid4(),
                ticket_id=queue_row.hubspot_ticket_id,
                queue_row=queue_row,
                selected_agent=locked_agent,
                eligibility_revision=locked_agent.availability_revision,
                desired_hubspot_owner_id=locked_agent.hubspot_owner_id,
                decision_snapshot={
                    "agent_id": str(locked_agent.pk),
                    "availability_revision": locked_agent.availability_revision,
                    "current_chats_before": locked_agent.current_simultaneous_chats - 1,
                    "max_chats": locked_agent.max_simultaneous_chats or 5,
                },
                decision_reason=reason,
                provider_request_classification="hubspot_owner_update",
                reserved_at=database_now,
            )
            logger.info(
                "assignment_attempt_reserved",
                attempt_id=str(attempt.pk),
                ticket_id=attempt.ticket_id,
                agent_id=str(locked_agent.pk),
                eligibility_revision=attempt.eligibility_revision,
            )
            return Reservation(attempt, "reserved")
    _defer_without_candidate(ticket_id)
    return Reservation(None, "candidate_changed")


def reserve_manual_assignment(
    *,
    ticket_id: str,
    agent_id: uuid.UUID,
    requested_by: str,
) -> Reservation:
    """Reserve an explicitly selected eligible agent for a manual assignment."""
    from apps.support.eligibility_service import evaluate_persisted_agent
    from apps.support.sat_service import sat_verify_agent_assignment_eligibility

    candidate = Agent.objects.get(pk=agent_id)
    captured_now = timezone.now()
    if settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED:
        local = evaluate_persisted_agent(candidate, captured_now)
        if not local.eligible:
            return Reservation(None, local.reason.value)
        remote = sat_verify_agent_assignment_eligibility(candidate, now=captured_now)
        if not remote.eligible:
            return Reservation(None, remote.reason.value)

    with transaction.atomic():
        now = _database_now()
        queue_row = NewConversation.objects.select_for_update().filter(hubspot_ticket_id=ticket_id).first()
        if queue_row is None:
            return Reservation(None, "queue_row_missing")
        existing = (
            AssignmentAttempt.objects.select_for_update().filter(ticket_id=ticket_id, state__in=LIVE_STATES).first()
        )
        if existing is not None:
            return Reservation(existing, "existing_attempt")
        agent = Agent.objects.select_for_update().get(pk=agent_id)
        decision = evaluate_persisted_agent(agent, now)
        eligible_now = (
            decision.eligible
            if settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED
            else agent.current_simultaneous_chats < (agent.max_simultaneous_chats or 5)
        )
        if not eligible_now or agent.availability_revision != candidate.availability_revision:
            return Reservation(None, "eligibility_revision_changed")
        claim_token = uuid.uuid4().hex
        queue_row.claim_owner_token = claim_token
        queue_row.claimed_at = now
        queue_row.claim_expires_at = now + timedelta(seconds=int(getattr(settings, "ASSIGNMENT_CLAIM_TTL_SECONDS", 90)))
        queue_row.assignment_attempts += 1
        queue_row.last_assignment_attempt_at = now
        queue_row.save(
            update_fields=[
                "claim_owner_token",
                "claimed_at",
                "claim_expires_at",
                "assignment_attempts",
                "last_assignment_attempt_at",
                "updated_at",
            ]
        )
        agent.current_simultaneous_chats += 1
        agent.last_assignment_at = now
        agent.updated_at = now
        agent.save(
            update_fields=[
                "current_simultaneous_chats",
                "last_assignment_at",
                "updated_at",
            ]
        )
        attempt = AssignmentAttempt.objects.create(
            idempotency_key=uuid.uuid4(),
            ticket_id=ticket_id,
            queue_row=queue_row,
            selected_agent=agent,
            eligibility_revision=agent.availability_revision,
            desired_hubspot_owner_id=agent.hubspot_owner_id,
            decision_snapshot={
                "agent_id": str(agent.pk),
                "availability_revision": agent.availability_revision,
                "manual": True,
            },
            decision_reason=(decision.reason.value if settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED else "manual_rollout"),
            assignment_type=AssignmentAttempt.AssignmentType.MANUAL,
            requested_by=requested_by,
            provider_request_classification="hubspot_owner_update",
            reserved_at=now,
        )
        return Reservation(attempt, "reserved")


def _defer_without_candidate(ticket_id: str | None) -> None:
    """Back off a queue row without blocking later ready tickets."""
    now = timezone.now()
    rows = NewConversation.objects.filter(
        automatic_assignment_eligible=True,
        queue_status__in=(
            NewConversation.QueueStatus.PENDING,
            NewConversation.QueueStatus.QUEUED,
        ),
    )
    if ticket_id is not None:
        rows = rows.filter(hubspot_ticket_id=ticket_id)
    row = rows.order_by("entered_queue_at", "id").first()
    if row is None:
        return
    row.queue_status = NewConversation.QueueStatus.QUEUED
    row.assignment_attempts += 1
    row.last_assignment_attempt_at = now
    row.next_assignment_attempt_at = now + timedelta(seconds=30)
    row.failure_code = "no_eligible_candidate"
    row.failure_message = "No authoritative eligible candidate was available."
    row.save(
        update_fields=[
            "queue_status",
            "assignment_attempts",
            "last_assignment_attempt_at",
            "next_assignment_attempt_at",
            "failure_code",
            "failure_message",
            "updated_at",
        ]
    )


def execute_assignment_attempt(attempt_id: uuid.UUID) -> str:
    """Apply HubSpot mutation and converge the durable attempt."""
    attempt = AssignmentAttempt.objects.select_related("selected_agent").get(pk=attempt_id)
    if attempt.state == AssignmentAttempt.State.COMPLETED:
        return "assigned"
    if attempt.state == AssignmentAttempt.State.EXTERNAL_APPLIED:
        finalize_assignment_attempt(attempt.pk)
        return "assigned"
    if attempt.state != AssignmentAttempt.State.RESERVED:
        return attempt.state

    try:
        get_hubspot_client().assign_ticket_owner(
            attempt.ticket_id,
            attempt.desired_hubspot_owner_id,
        )
    except HubSpotResourceNotFoundError:
        compensate_assignment_attempt(
            attempt.pk,
            retryable=False,
            error_code="hubspot_ticket_not_found",
            quarantine=True,
        )
        return "stale_ticket"
    except HubSpotAPIError as exc:
        return reconcile_ambiguous_attempt(attempt.pk, exc)

    with transaction.atomic():
        locked = AssignmentAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.state == AssignmentAttempt.State.RESERVED:
            now = _database_now()
            locked.state = AssignmentAttempt.State.EXTERNAL_APPLIED
            locked.external_applied_at = now
            locked.provider_result_classification = "success"
            locked.last_error_code = ""
            locked.save(
                update_fields=[
                    "state",
                    "external_applied_at",
                    "provider_result_classification",
                    "last_error_code",
                    "updated_at",
                ]
            )
    finalize_assignment_attempt(attempt.pk)
    return "assigned"


def finalize_assignment_attempt(attempt_id: uuid.UUID) -> AssignmentAttempt:
    """Finalize exactly once after HubSpot is known to hold the target owner."""
    with transaction.atomic():
        attempt = (
            AssignmentAttempt.objects.select_for_update(of=("self",))
            .select_related("selected_agent", "queue_row")
            .get(pk=attempt_id)
        )
        if attempt.state == AssignmentAttempt.State.COMPLETED:
            return attempt
        if attempt.state != AssignmentAttempt.State.EXTERNAL_APPLIED:
            raise ValueError(f"attempt {attempt.pk} is not externally applied")

        now = _database_now()
        queue_row = attempt.queue_row
        wait_seconds: Decimal | None = None
        if queue_row is not None and queue_row.entered_queue_at:
            wait_seconds = Decimal(str(round((now - queue_row.entered_queue_at).total_seconds(), 2)))
        defaults = {
            "agent": attempt.selected_agent,
            "hubspot_owner_id": attempt.desired_hubspot_owner_id,
            "agent_name": attempt.selected_agent.name,
            "assigned_at": now,
            "queue_wait_seconds": wait_seconds,
        }
        if queue_row is not None:
            defaults.update(
                {
                    "pipeline_id": queue_row.pipeline_id,
                    "entered_queue_at": queue_row.entered_queue_at,
                    "contact_name": queue_row.contact_name,
                    "contact_email": queue_row.contact_email,
                    "priority": queue_row.priority,
                    "subject": queue_row.subject,
                }
            )
        AssignedConversation.objects.update_or_create(
            hubspot_ticket_id=attempt.ticket_id,
            defaults=defaults,
        )
        AssignmentLog.objects.update_or_create(
            assignment_attempt=attempt,
            defaults={
                "ticket_id": attempt.ticket_id,
                "agent": attempt.selected_agent,
                "agent_name": attempt.selected_agent.name,
                "hubspot_owner_id": attempt.desired_hubspot_owner_id,
                "assignment_type": attempt.assignment_type,
                "assigned_by": attempt.requested_by or None,
                "pipeline_id": queue_row.pipeline_id if queue_row else None,
                "entered_queue_at": queue_row.entered_queue_at if queue_row else None,
                "queue_wait_seconds": wait_seconds,
            },
        )
        Agent.objects.filter(pk=attempt.selected_agent_id).update(
            total_assignments=F("total_assignments") + 1,
        )
        if queue_row is not None:
            queue_row.delete()
            attempt.queue_row = None
        attempt.state = AssignmentAttempt.State.COMPLETED
        attempt.finalized_at = now
        attempt.next_retry_at = None
        attempt.save(
            update_fields=[
                "state",
                "finalized_at",
                "next_retry_at",
                "updated_at",
            ]
        )
        return attempt


def compensate_assignment_attempt(
    attempt_id: uuid.UUID,
    *,
    retryable: bool,
    error_code: str,
    quarantine: bool = False,
    repair_required: bool = False,
) -> AssignmentAttempt:
    """Release capacity and update retry/repair state exactly once."""
    with transaction.atomic():
        attempt = (
            AssignmentAttempt.objects.select_for_update(of=("self",)).select_related("queue_row").get(pk=attempt_id)
        )
        if (
            attempt.state
            in (
                AssignmentAttempt.State.COMPLETED,
                AssignmentAttempt.State.COMPENSATED,
            )
            or attempt.compensated_at is not None
        ):
            return attempt
        now = _database_now()
        attempt.compensation_started_at = attempt.compensation_started_at or now
        if attempt.compensated_at is None:
            Agent.objects.filter(pk=attempt.selected_agent_id).update(
                current_simultaneous_chats=Greatest(
                    F("current_simultaneous_chats") - 1,
                    Value(0),
                ),
                updated_at=now,
            )
            attempt.compensated_at = now
        attempt.retry_count += 1
        attempt.last_error_code = error_code
        attempt.provider_result_classification = error_code
        if repair_required:
            attempt.state = AssignmentAttempt.State.REPAIR_REQUIRED
            attempt.next_retry_at = None
        elif retryable:
            exponent = min(max(attempt.retry_count - 1, 0), 5)
            attempt.state = AssignmentAttempt.State.RETRYABLE
            attempt.next_retry_at = now + timedelta(seconds=min(60 * (2**exponent), 1800))
        else:
            attempt.state = AssignmentAttempt.State.COMPENSATED
            attempt.next_retry_at = None

        queue_row = attempt.queue_row
        if queue_row is not None:
            queue_row.claim_owner_token = ""
            queue_row.claim_expires_at = None
            queue_row.claimed_at = None
            queue_row.last_assignment_attempt_at = now
            queue_row.next_assignment_attempt_at = attempt.next_retry_at
            queue_row.failure_code = error_code
            queue_row.failure_message = "Assignment did not reach a confirmed provider state."
            if quarantine:
                queue_row.queue_status = NewConversation.QueueStatus.FAILED
            else:
                queue_row.queue_status = NewConversation.QueueStatus.QUEUED
            queue_row.save(
                update_fields=[
                    "claim_owner_token",
                    "claim_expires_at",
                    "claimed_at",
                    "last_assignment_attempt_at",
                    "next_assignment_attempt_at",
                    "failure_code",
                    "failure_message",
                    "queue_status",
                    "updated_at",
                ]
            )
        attempt.save(
            update_fields=[
                "state",
                "compensation_started_at",
                "compensated_at",
                "retry_count",
                "next_retry_at",
                "last_error_code",
                "provider_result_classification",
                "updated_at",
            ]
        )
        return attempt


def reconcile_ambiguous_attempt(
    attempt_id: uuid.UUID,
    provider_error: HubSpotAPIError | None = None,
) -> str:
    """Read the provider owner and converge without assuming mutation failure."""
    attempt = AssignmentAttempt.objects.get(pk=attempt_id)
    error_code = provider_error.error_code if provider_error else "ambiguous_provider_result"
    if provider_error is not None and error_code == "unknown" and provider_error.external_status is not None:
        error_code = f"hubspot_http_{provider_error.external_status}"
    try:
        ticket = get_hubspot_client().get_ticket_details(attempt.ticket_id)
    except Exception:
        compensate_assignment_attempt(
            attempt.pk,
            retryable=False,
            repair_required=True,
            error_code=f"{error_code}_owner_unreadable",
        )
        return "repair_required"

    raw_owner = ticket.get("owner_id")
    current_owner = int(raw_owner) if str(raw_owner).isdigit() else None
    if current_owner == attempt.desired_hubspot_owner_id:
        with transaction.atomic():
            locked = AssignmentAttempt.objects.select_for_update().get(pk=attempt.pk)
            if locked.state != AssignmentAttempt.State.COMPLETED:
                locked.state = AssignmentAttempt.State.EXTERNAL_APPLIED
                locked.external_applied_at = locked.external_applied_at or _database_now()
                locked.provider_result_classification = "confirmed_by_read"
                locked.save(
                    update_fields=[
                        "state",
                        "external_applied_at",
                        "provider_result_classification",
                        "updated_at",
                    ]
                )
        finalize_assignment_attempt(attempt.pk)
        return "assigned"
    if current_owner in (None, attempt.prior_observed_owner_id) and (
        provider_error is None or provider_error.retryable
    ):
        compensate_assignment_attempt(
            attempt.pk,
            retryable=True,
            error_code=error_code,
        )
        return "retryable_external_error"
    compensate_assignment_attempt(
        attempt.pk,
        retryable=False,
        repair_required=True,
        error_code=f"{error_code}_owner_conflict",
    )
    return "repair_required"


def retry_assignment_attempt(attempt_id: uuid.UUID) -> str:
    """Re-reserve a due retry and execute it without creating another attempt."""
    attempt = AssignmentAttempt.objects.select_related("selected_agent").get(pk=attempt_id)
    if attempt.state != AssignmentAttempt.State.RETRYABLE:
        return attempt.state
    from apps.support.eligibility_service import evaluate_persisted_agent
    from apps.support.sat_service import sat_verify_agent_assignment_eligibility

    captured_now = timezone.now()
    if not evaluate_persisted_agent(attempt.selected_agent, captured_now).eligible:
        return "retryable"
    remote = sat_verify_agent_assignment_eligibility(attempt.selected_agent, now=captured_now)
    if not remote.eligible:
        return "retryable"
    with transaction.atomic():
        locked_attempt = AssignmentAttempt.objects.select_for_update().get(pk=attempt.pk)
        agent = Agent.objects.select_for_update().get(pk=attempt.selected_agent_id)
        database_now = _database_now()
        decision = evaluate_persisted_agent(agent, database_now)
        if locked_attempt.state != AssignmentAttempt.State.RETRYABLE or not decision.eligible:
            return locked_attempt.state
        agent.current_simultaneous_chats += 1
        agent.last_assignment_at = database_now
        agent.updated_at = database_now
        agent.save(
            update_fields=[
                "current_simultaneous_chats",
                "last_assignment_at",
                "updated_at",
            ]
        )
        locked_attempt.state = AssignmentAttempt.State.RESERVED
        locked_attempt.reserved_at = database_now
        locked_attempt.compensation_started_at = None
        locked_attempt.compensated_at = None
        locked_attempt.next_retry_at = None
        locked_attempt.eligibility_revision = agent.availability_revision
        locked_attempt.save(
            update_fields=[
                "state",
                "reserved_at",
                "compensation_started_at",
                "compensated_at",
                "next_retry_at",
                "eligibility_revision",
                "updated_at",
            ]
        )
    return execute_assignment_attempt(attempt.pk)


def repair_assignment_attempts(*, limit: int = 100) -> dict[str, int]:
    """Converge bounded batches of stale, retryable, or externally-applied attempts."""
    now = timezone.now()
    stale_before = now - timedelta(seconds=int(getattr(settings, "ASSIGNMENT_STUCK_AFTER_SECONDS", 120)))
    attempts = list(
        AssignmentAttempt.objects.filter(
            Q(state=AssignmentAttempt.State.EXTERNAL_APPLIED)
            | Q(
                state=AssignmentAttempt.State.RETRYABLE,
                next_retry_at__lte=now,
            )
            | Q(
                state=AssignmentAttempt.State.RESERVED,
                reserved_at__lte=stale_before,
            )
            | Q(state=AssignmentAttempt.State.REPAIR_REQUIRED)
        ).order_by("updated_at")[:limit]
    )
    counts = {"scanned": len(attempts), "assigned": 0, "retryable": 0, "repair_required": 0}
    for attempt in attempts:
        if attempt.state == AssignmentAttempt.State.EXTERNAL_APPLIED:
            outcome = "assigned"
            finalize_assignment_attempt(attempt.pk)
        elif attempt.state == AssignmentAttempt.State.RETRYABLE:
            outcome = retry_assignment_attempt(attempt.pk)
        else:
            outcome = reconcile_ambiguous_attempt(attempt.pk)
        if outcome in counts:
            counts[outcome] += 1
    return counts


def purge_terminal_assignment_attempts(*, days: int = 30, limit: int = 500) -> int:
    """Delete a bounded batch of terminal attempts older than retention."""
    cutoff = timezone.now() - timedelta(days=days)
    ids = list(
        AssignmentAttempt.objects.filter(
            state__in=(
                AssignmentAttempt.State.COMPLETED,
                AssignmentAttempt.State.COMPENSATED,
            ),
            updated_at__lt=cutoff,
        )
        .order_by("updated_at")
        .values_list("pk", flat=True)[:limit]
    )
    if not ids:
        return 0
    deleted, _ = AssignmentAttempt.objects.filter(pk__in=ids).delete()
    return deleted
