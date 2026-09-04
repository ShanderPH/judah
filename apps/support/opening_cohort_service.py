"""Durable opening-window cohort barrier for automatic assignments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.functions import Coalesce

from apps.support.helpdesk_calendar.service import OperationalWindow, resolve_operational_window
from apps.support.models import Agent, NewConversation, OpeningAssignmentCohort

logger = structlog.get_logger(__name__)
_RECHECK_JITTER_SECONDS = 2


class CohortBarrierOutcome(StrEnum):
    """Exhaustive outcomes of one barrier evaluation."""

    NOT_APPLICABLE = "not_applicable"
    SHADOW_WOULD_DEFER = "shadow_would_defer"
    DEFERRED = "deferred"
    RELEASED_ALL_SETTLED = "released_all_settled"
    RELEASED_DEADLINE = "released_deadline"


@dataclass(frozen=True, slots=True)
class CohortBarrierDecision:
    """PII-free result returned to the reservation protocol."""

    outcome: CohortBarrierOutcome
    cohort_id: uuid.UUID | None = None
    recheck_at: datetime | None = None

    @property
    def deferred(self) -> bool:
        """Return whether enforcement must stop this reservation."""
        return self.outcome == CohortBarrierOutcome.DEFERRED


def _emit(name: str, value: int | float = 1, **labels: str) -> None:
    """Emit one bounded-cardinality cohort metric."""
    from apps.webhooks.metrics import emit_metric

    emit_metric(name, value, **labels)


def _candidate_snapshots() -> list[Agent]:
    """Return initial eligible/stabilizing agents with identity and capacity."""
    from apps.support.availability_runtime import (
        automatic_assignment_canary_agent_ids,
        is_automatic_assignment_canary_configured,
    )

    candidates = (
        Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True))
        .filter(auto_assign_enabled=True, hubspot_user_id__isnull=False)
        .exclude(hubspot_user_id="")
        .filter(current_simultaneous_chats__lt=Coalesce(F("max_simultaneous_chats"), 5))
        .filter(Q(eligibility_state=Agent.EligibilityState.ELIGIBLE) | Q(eligibility_reason="stabilizing"))
    )
    if is_automatic_assignment_canary_configured():
        candidates = candidates.filter(pk__in=automatic_assignment_canary_agent_ids())
    return list(candidates.order_by("id"))


def _cohort_defaults(
    *,
    window: OperationalWindow,
    agents: list[Agent],
    now: datetime,
) -> dict[str, object] | None:
    eligible = [agent for agent in agents if agent.eligibility_state == Agent.EligibilityState.ELIGIBLE]
    stabilizing = [agent for agent in agents if agent.eligibility_reason == "stabilizing"]
    if not eligible or not stabilizing:
        return None
    online_since = [agent.availability_online_since for agent in agents]
    if any(value is None for value in online_since):
        observed_at = now
        logger.warning("opening_cohort_inconsistent_online_since", member_count=len(agents))
    else:
        observed_at = max(window.start_at, min(value for value in online_since if value is not None))
    stable_seconds = int(settings.AVAILABILITY_STABLE_SECONDS)
    heartbeat_seconds = int(settings.SAT_HEARTBEAT_INTERVAL_SECONDS)
    deadline_at = observed_at + timedelta(seconds=stable_seconds + heartbeat_seconds)
    if now >= deadline_at:
        return None
    stabilizing_eta = max(
        (agent.availability_online_since or now) + timedelta(seconds=stable_seconds) for agent in stabilizing
    )
    recheck_at = min(deadline_at, max(now, stabilizing_eta) + timedelta(seconds=_RECHECK_JITTER_SECONDS))
    return {
        "cohort_observed_at": observed_at,
        "recheck_at": recheck_at,
        "deadline_at": deadline_at,
        "member_agent_ids": [str(agent.pk) for agent in agents],
        "initial_eligible_count": len(eligible),
        "initial_stabilizing_count": len(stabilizing),
    }


def _locked_get_or_create(
    *, window: OperationalWindow, agents: list[Agent], now: datetime
) -> tuple[OpeningAssignmentCohort | None, bool]:
    cohort = OpeningAssignmentCohort.objects.select_for_update().filter(window_started_at=window.start_at).first()
    if cohort is not None:
        return cohort, False
    defaults = _cohort_defaults(window=window, agents=agents, now=now)
    if defaults is None:
        return None, False
    try:
        with transaction.atomic():
            cohort = OpeningAssignmentCohort.objects.create(window_started_at=window.start_at, **defaults)
        return cohort, True
    except IntegrityError:
        cohort = OpeningAssignmentCohort.objects.select_for_update().get(window_started_at=window.start_at)
        return cohort, False


def _release(
    cohort: OpeningAssignmentCohort,
    *,
    reason: OpeningAssignmentCohort.ReleaseReason,
    now: datetime,
) -> None:
    cohort.state = OpeningAssignmentCohort.State.RELEASED
    cohort.release_reason = reason
    cohort.released_at = now
    cohort.save(update_fields=["state", "release_reason", "released_at", "updated_at"])
    duration = max(0.0, (now - cohort.cohort_observed_at).total_seconds())
    member_ids = [uuid.UUID(value) for value in cohort.member_agent_ids]
    final_eligible = Agent.objects.filter(
        pk__in=member_ids,
        eligibility_state=Agent.EligibilityState.ELIGIBLE,
    ).count()
    final_stabilizing = Agent.objects.filter(pk__in=member_ids, eligibility_reason="stabilizing").count()
    _emit("assignment_cohort_barrier_released_total", reason=reason)
    _emit("assignment_cohort_barrier_duration_seconds", duration, kind="histogram", reason=reason)
    _emit("assignment_cohort_final_eligible", final_eligible, kind="gauge")
    _emit("assignment_cohort_final_stabilizing", final_stabilizing, kind="gauge")
    logger.info("opening_cohort_released", cohort_id=str(cohort.pk), reason=reason, duration_seconds=duration)


def _schedule_recheck(cohort: OpeningAssignmentCohort, now: datetime) -> None:
    if cohort.callback_scheduled_at is not None:
        return
    cohort.callback_scheduled_at = now
    cohort.save(update_fields=["callback_scheduled_at", "updated_at"])
    cohort_id = str(cohort.pk)
    eta = cohort.recheck_at

    def publish() -> None:
        from apps.support.tasks import task_recheck_opening_assignment_cohort

        try:
            task_recheck_opening_assignment_cohort.apply_async(args=[cohort_id], eta=eta)
            _emit("assignment_cohort_callbacks_total", result="published")
        except Exception as exc:
            _emit("assignment_cohort_callbacks_total", result="publish_failed")
            logger.warning(
                "opening_cohort_callback_publish_failed",
                cohort_id=cohort_id,
                exception_type=type(exc).__name__,
            )

    transaction.on_commit(publish)


def evaluate_opening_cohort_barrier(
    queue_row: NewConversation,
    *,
    now: datetime,
) -> CohortBarrierDecision:
    """Create/evaluate the frozen cohort before any assignment reservation write."""
    mode = str(settings.OPENING_COHORT_BARRIER_MODE)
    if mode == "off":
        return CohortBarrierDecision(CohortBarrierOutcome.NOT_APPLICABLE)
    window = resolve_operational_window(now)
    if window is None or queue_row.entered_queue_at >= window.start_at:
        return CohortBarrierDecision(CohortBarrierOutcome.NOT_APPLICABLE)

    with transaction.atomic():
        agents = _candidate_snapshots()
        cohort, created = _locked_get_or_create(window=window, agents=agents, now=now)
        if cohort is None:
            return CohortBarrierDecision(CohortBarrierOutcome.NOT_APPLICABLE)
        if cohort.state == OpeningAssignmentCohort.State.RELEASED:
            outcome = (
                CohortBarrierOutcome.RELEASED_DEADLINE
                if cohort.release_reason == OpeningAssignmentCohort.ReleaseReason.DEADLINE
                else CohortBarrierOutcome.RELEASED_ALL_SETTLED
            )
            return CohortBarrierDecision(outcome, cohort.pk, cohort.recheck_at)

        member_ids = [uuid.UUID(value) for value in cohort.member_agent_ids]
        stabilizing_count = (
            Agent.objects.filter(pk__in=member_ids, eligibility_reason="stabilizing")
            .filter(Q(is_active=True) | Q(is_active__isnull=True))
            .filter(
                auto_assign_enabled=True,
                current_simultaneous_chats__lt=Coalesce(F("max_simultaneous_chats"), 5),
            )
            .count()
        )
        if stabilizing_count == 0:
            _release(cohort, reason=OpeningAssignmentCohort.ReleaseReason.ALL_SETTLED, now=now)
            return CohortBarrierDecision(CohortBarrierOutcome.RELEASED_ALL_SETTLED, cohort.pk, cohort.recheck_at)
        if now >= cohort.deadline_at:
            _release(cohort, reason=OpeningAssignmentCohort.ReleaseReason.DEADLINE, now=now)
            return CohortBarrierDecision(CohortBarrierOutcome.RELEASED_DEADLINE, cohort.pk, cohort.recheck_at)

        _schedule_recheck(cohort, now)
        if created:
            _emit("assignment_cohort_barrier_started_total", mode=mode)
            _emit("assignment_cohort_initial_eligible", cohort.initial_eligible_count, kind="gauge")
            _emit("assignment_cohort_initial_stabilizing", cohort.initial_stabilizing_count, kind="gauge")
            protected_backlog = NewConversation.objects.filter(
                automatic_assignment_eligible=True,
                entered_queue_at__lt=cohort.window_started_at,
                queue_status__in=(NewConversation.QueueStatus.PENDING, NewConversation.QueueStatus.QUEUED),
            ).count()
            _emit("assignment_cohort_protected_backlog", protected_backlog, kind="gauge")
            logger.info(
                "opening_cohort_started",
                cohort_id=str(cohort.pk),
                mode=mode,
                eligible_count=cohort.initial_eligible_count,
                stabilizing_count=cohort.initial_stabilizing_count,
            )
        if mode == "shadow":
            return CohortBarrierDecision(CohortBarrierOutcome.SHADOW_WOULD_DEFER, cohort.pk, cohort.recheck_at)
        if queue_row.next_assignment_attempt_at != cohort.recheck_at:
            queue_row.next_assignment_attempt_at = cohort.recheck_at
            queue_row.save(update_fields=["next_assignment_attempt_at", "updated_at"])
        return CohortBarrierDecision(CohortBarrierOutcome.DEFERRED, cohort.pk, cohort.recheck_at)
