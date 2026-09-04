"""Opening-window assignment cohort barrier contract tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.db import close_old_connections, connection, transaction
from django.test import override_settings

from apps.support.durable_assignment_service import reserve_next_assignment
from apps.support.helpdesk_calendar.service import resolve_operational_window
from apps.support.matchmaker_service import matchmaker_drain_queue
from apps.support.models import Agent, AssignmentAttempt, NewConversation, OpeningAssignmentCohort
from apps.support.opening_cohort_service import (
    CohortBarrierOutcome,
    evaluate_opening_cohort_barrier,
)

pytestmark = pytest.mark.django_db(transaction=True)
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _agent(*, owner_id: int, eligibility_reason: str, observed_at: datetime) -> Agent:
    eligible = eligibility_reason == "eligible"
    return Agent.objects.create(
        name=f"Agent {owner_id}",
        agent_email=f"opening-{owner_id}@example.test",
        hubspot_owner_id=owner_id,
        hubspot_user_id=str(owner_id),
        status_enum=Agent.StatusEnum.ONLINE if eligible else Agent.StatusEnum.AWAY,
        is_active=True,
        auto_assign_enabled=True,
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        availability_observed_at=observed_at,
        availability_online_since=observed_at,
        availability_sample_count=2 if eligible else 1,
        eligibility_state=(Agent.EligibilityState.ELIGIBLE if eligible else Agent.EligibilityState.INELIGIBLE),
        eligibility_reason=eligibility_reason,
        availability_revision=1,
    )


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    OPENING_COHORT_BARRIER_MODE="enforce",
    AVAILABILITY_STABLE_SECONDS=30,
    SAT_HEARTBEAT_INTERVAL_SECONDS=30,
)
def test_backlog_waits_without_reservation_while_initial_cohort_stabilizes() -> None:
    """The common reservation path must defer before any durable assignment write."""
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    observed_at = window_start + timedelta(seconds=5)
    eligible = _agent(owner_id=8101, eligibility_reason="eligible", observed_at=observed_at)
    _agent(owner_id=8102, eligibility_reason="stabilizing", observed_at=observed_at)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="opening-backlog",
        entered_queue_at=window_start - timedelta(minutes=2),
        automatic_assignment_eligible=True,
    )

    with (
        patch(
            "apps.support.durable_assignment_service._verify_candidates",
            return_value=[(eligible, "eligible")],
        ) as verify_candidates,
        patch(
            "apps.support.durable_assignment_service.timezone.now",
            return_value=window_start + timedelta(seconds=10),
        ),
        patch(
            "apps.support.durable_assignment_service._database_now",
            return_value=window_start + timedelta(seconds=10),
        ),
        patch(
            "apps.support.helpdesk_calendar.service.timezone.now",
            return_value=window_start + timedelta(seconds=10),
        ),
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
    ):
        reservation = reserve_next_assignment(queue_row.hubspot_ticket_id)

    assert reservation.reason == "deferred_stabilizing_cohort"
    verify_candidates.assert_not_called()
    assert reservation.attempt is None
    assert AssignmentAttempt.objects.count() == 0
    eligible.refresh_from_db()
    assert eligible.current_simultaneous_chats == 0


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    OPENING_COHORT_BARRIER_MODE="enforce",
)
def test_drain_reports_defer_and_continues_without_assignment_effect() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    now = window_start + timedelta(seconds=5)
    _agent(owner_id=8151, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8152, eligibility_reason="stabilizing", observed_at=window_start)
    NewConversation.objects.create(
        hubspot_ticket_id="drain-backlog",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )

    with (
        patch("apps.support.durable_assignment_service._database_now", return_value=now),
        patch("apps.support.queue_service.timezone.now", return_value=now),
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
    ):
        result = matchmaker_drain_queue()

    assert result["deferred"] == 1
    assert result["assigned"] == 0
    assert AssignmentAttempt.objects.count() == 0


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    OPENING_COHORT_BARRIER_MODE="enforce",
)
def test_single_task_reaches_the_same_common_gate() -> None:
    from apps.support.tasks import task_matchmaker_assign_single

    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    now = window_start + timedelta(seconds=5)
    _agent(owner_id=8171, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8172, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="single-backlog",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )

    with (
        patch("apps.support.matchmaker_service.enqueue_new_ticket", return_value=queue_row),
        patch("apps.support.sat_service.sat_heartbeat", return_value={"agents_checked": 2}),
        patch("apps.support.durable_assignment_service._database_now", return_value=now),
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
        patch("apps.support.owned_cache_lock.OwnedCacheLock.acquire", return_value=True),
        patch("apps.support.owned_cache_lock.OwnedCacheLock.release"),
    ):
        assigned = task_matchmaker_assign_single.run(queue_row.hubspot_ticket_id)

    assert assigned is False
    assert AssignmentAttempt.objects.count() == 0
    queue_row.refresh_from_db()
    assert queue_row.next_assignment_attempt_at is not None


@pytest.mark.parametrize(
    ("mode", "expected_reason", "cohort_count"),
    [("off", "reserved", 0), ("shadow", "reserved", 1)],
)
@override_settings(ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True)
def test_off_and_shadow_never_change_reservation(
    mode: str,
    expected_reason: str,
    cohort_count: int,
) -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    now = window_start + timedelta(seconds=10)
    eligible = _agent(owner_id=8201, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8202, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id=f"mode-{mode}",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )
    with (
        override_settings(OPENING_COHORT_BARRIER_MODE=mode),
        patch("apps.support.durable_assignment_service._verify_candidates", return_value=[(eligible, "eligible")]),
        patch("apps.support.durable_assignment_service.timezone.now", return_value=now),
        patch("apps.support.durable_assignment_service._database_now", return_value=now),
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
    ):
        reservation = reserve_next_assignment(queue_row.hubspot_ticket_id)

    assert reservation.reason == expected_reason
    assert OpeningAssignmentCohort.objects.count() == cohort_count
    queue_row.refresh_from_db()
    assert queue_row.next_assignment_attempt_at is None


@override_settings(
    OPENING_COHORT_BARRIER_MODE="enforce",
    AVAILABILITY_STABLE_SECONDS=30,
    SAT_HEARTBEAT_INTERVAL_SECONDS=30,
)
def test_post_opening_ticket_bypasses_while_backlog_remains_deferred() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    now = window_start + timedelta(seconds=10)
    eligible = _agent(owner_id=8301, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8302, eligibility_reason="stabilizing", observed_at=window_start)
    backlog = NewConversation.objects.create(
        hubspot_ticket_id="old-backlog",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )
    recent = NewConversation.objects.create(
        hubspot_ticket_id="post-opening",
        entered_queue_at=window_start + timedelta(seconds=1),
        automatic_assignment_eligible=True,
    )
    with (
        patch("apps.support.durable_assignment_service._verify_candidates", return_value=[(eligible, "eligible")]),
        patch("apps.support.durable_assignment_service.timezone.now", return_value=now),
        patch("apps.support.durable_assignment_service._database_now", return_value=now),
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
    ):
        first = reserve_next_assignment()
        second = reserve_next_assignment(exclude_queue_row_ids={backlog.pk})

    assert first.reason == "deferred_stabilizing_cohort"
    assert second.reason == "reserved"
    assert second.queue_row_id == recent.pk
    backlog.refresh_from_db()
    assert backlog.assignment_attempts == 0


@override_settings(
    OPENING_COHORT_BARRIER_MODE="enforce",
    AVAILABILITY_STABLE_SECONDS=30,
    SAT_HEARTBEAT_INTERVAL_SECONDS=30,
)
def test_members_and_deadline_do_not_change_when_a_late_agent_arrives() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    now = window_start + timedelta(seconds=10)
    _agent(owner_id=8401, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8402, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="frozen-members",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )
    with patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async") as publish:
        first = evaluate_opening_cohort_barrier(queue_row, now=now)
        cohort = OpeningAssignmentCohort.objects.get()
        members = list(cohort.member_agent_ids)
        deadline = cohort.deadline_at
        _agent(owner_id=8403, eligibility_reason="stabilizing", observed_at=now)
        second = evaluate_opening_cohort_barrier(queue_row, now=now + timedelta(seconds=5))

    cohort.refresh_from_db()
    assert first.outcome == CohortBarrierOutcome.DEFERRED
    assert second.outcome == CohortBarrierOutcome.DEFERRED
    assert cohort.member_agent_ids == members
    assert cohort.deadline_at == deadline
    publish.assert_called_once()


@override_settings(
    OPENING_COHORT_BARRIER_MODE="enforce",
    AVAILABILITY_STABLE_SECONDS=30,
    SAT_HEARTBEAT_INTERVAL_SECONDS=30,
)
def test_all_settled_releases_without_renewing_cohort() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    now = window_start + timedelta(seconds=10)
    _agent(owner_id=8501, eligibility_reason="eligible", observed_at=window_start)
    stabilizing = _agent(owner_id=8502, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="all-settled",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )
    with (
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
        patch("apps.webhooks.metrics.emit_metric"),
    ):
        assert evaluate_opening_cohort_barrier(queue_row, now=now).deferred is True
        stabilizing.eligibility_reason = "remote_away"
        stabilizing.save(update_fields=["eligibility_reason"])
        decision = evaluate_opening_cohort_barrier(queue_row, now=now + timedelta(seconds=20))

    cohort = OpeningAssignmentCohort.objects.get()
    assert decision.outcome == CohortBarrierOutcome.RELEASED_ALL_SETTLED
    assert cohort.release_reason == OpeningAssignmentCohort.ReleaseReason.ALL_SETTLED


@override_settings(
    OPENING_COHORT_BARRIER_MODE="enforce",
    AVAILABILITY_STABLE_SECONDS=30,
    SAT_HEARTBEAT_INTERVAL_SECONDS=30,
)
def test_deadline_releases_but_does_not_make_stabilizing_agent_eligible() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    _agent(owner_id=8601, eligibility_reason="eligible", observed_at=window_start)
    stabilizing = _agent(owner_id=8602, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="deadline",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )
    with (
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
        patch("apps.webhooks.metrics.emit_metric"),
    ):
        evaluate_opening_cohort_barrier(queue_row, now=window_start + timedelta(seconds=10))
        decision = evaluate_opening_cohort_barrier(queue_row, now=window_start + timedelta(seconds=61))

    cohort = OpeningAssignmentCohort.objects.get()
    stabilizing.refresh_from_db()
    assert decision.outcome == CohortBarrierOutcome.RELEASED_DEADLINE
    assert cohort.release_reason == OpeningAssignmentCohort.ReleaseReason.DEADLINE
    assert stabilizing.eligibility_state == Agent.EligibilityState.INELIGIBLE


def test_operational_window_is_half_open_and_timezone_aware() -> None:
    opening = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    inside = resolve_operational_window(opening)

    assert inside is not None
    assert inside.start_at.isoformat() == "2026-09-04T12:00:00+00:00"
    assert inside.end_at.isoformat() == "2026-09-04T20:50:00+00:00"
    assert resolve_operational_window(datetime(2026, 9, 4, 17, 50, tzinfo=SAO_PAULO)) is None


@override_settings(OPENING_COHORT_BARRIER_MODE="enforce")
def test_only_stabilizing_agents_preserve_no_agent_behavior() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    _agent(owner_id=8701, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="only-stabilizing",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )

    decision = evaluate_opening_cohort_barrier(queue_row, now=window_start + timedelta(seconds=5))

    assert decision.outcome == CohortBarrierOutcome.NOT_APPLICABLE
    assert OpeningAssignmentCohort.objects.count() == 0


@override_settings(OPENING_COHORT_BARRIER_MODE="enforce")
def test_rollback_never_publishes_callback() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    _agent(owner_id=8801, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8802, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="rollback",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )

    with (
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async") as publish,
        pytest.raises(RuntimeError, match="rollback"),
        transaction.atomic(),
    ):
        evaluate_opening_cohort_barrier(queue_row, now=window_start + timedelta(seconds=5))
        raise RuntimeError("rollback")

    publish.assert_not_called()
    assert OpeningAssignmentCohort.objects.count() == 0


def test_recheck_task_is_noop_after_release() -> None:
    from apps.support.tasks import task_recheck_opening_assignment_cohort

    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    cohort = OpeningAssignmentCohort.objects.create(
        window_started_at=window_start,
        cohort_observed_at=window_start,
        recheck_at=window_start + timedelta(seconds=30),
        deadline_at=window_start + timedelta(seconds=60),
        member_agent_ids=[],
        initial_eligible_count=1,
        initial_stabilizing_count=1,
        state=OpeningAssignmentCohort.State.RELEASED,
        release_reason=OpeningAssignmentCohort.ReleaseReason.ALL_SETTLED,
        released_at=window_start + timedelta(seconds=20),
    )
    with (
        patch("apps.support.sat_service.sat_heartbeat") as heartbeat,
        patch("apps.webhooks.metrics.emit_metric"),
    ):
        result = task_recheck_opening_assignment_cohort(str(cohort.pk))

    assert result == {"result": "released"}
    heartbeat.assert_not_called()


@override_settings(OPENING_COHORT_BARRIER_MODE="enforce")
def test_publish_failure_stays_deferred_and_telemetry_contains_no_pii() -> None:
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    eligible = _agent(owner_id=8851, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8852, eligibility_reason="stabilizing", observed_at=window_start)
    queue_row = NewConversation.objects.create(
        hubspot_ticket_id="publish-failure",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )
    with (
        patch(
            "apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async",
            side_effect=RuntimeError("broker unavailable"),
        ),
        patch("apps.webhooks.metrics.emit_metric") as metric,
        patch("apps.support.opening_cohort_service.logger") as cohort_logger,
    ):
        decision = evaluate_opening_cohort_barrier(queue_row, now=window_start + timedelta(seconds=5))

    assert decision.deferred is True
    assert AssignmentAttempt.objects.count() == 0
    telemetry = f"{metric.call_args_list!s} {cohort_logger.method_calls!s}"
    assert eligible.name not in telemetry
    assert eligible.agent_email not in telemetry
    assert queue_row.hubspot_ticket_id not in telemetry


@pytest.mark.integration
@override_settings(
    OPENING_COHORT_BARRIER_MODE="enforce",
    AVAILABILITY_STABLE_SECONDS=30,
    SAT_HEARTBEAT_INTERVAL_SECONDS=30,
)
def test_concurrent_reservations_create_one_cohort_and_zero_attempts() -> None:
    """Separate PostgreSQL connections must converge before any reservation write."""
    if connection.vendor != "postgresql":
        pytest.skip("Opening cohort locking requires disposable PostgreSQL.")
    window_start = datetime(2026, 9, 4, 9, 0, tzinfo=SAO_PAULO)
    now = window_start + timedelta(seconds=5)
    _agent(owner_id=8901, eligibility_reason="eligible", observed_at=window_start)
    _agent(owner_id=8902, eligibility_reason="stabilizing", observed_at=window_start)
    NewConversation.objects.create(
        hubspot_ticket_id="concurrent-opening",
        entered_queue_at=window_start - timedelta(minutes=1),
        automatic_assignment_eligible=True,
    )

    def reserve() -> str:
        close_old_connections()
        try:
            return str(reserve_next_assignment().reason)
        finally:
            close_old_connections()

    with (
        patch("apps.support.durable_assignment_service.timezone.now", return_value=now),
        patch("apps.support.durable_assignment_service._database_now", return_value=now),
        patch("apps.support.tasks.task_recheck_opening_assignment_cohort.apply_async"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(pool.map(lambda _index: reserve(), range(2)))

    assert set(outcomes) <= {"deferred_stabilizing_cohort", "queue_empty_or_claimed"}
    assert "deferred_stabilizing_cohort" in outcomes
    assert OpeningAssignmentCohort.objects.count() == 1
    assert AssignmentAttempt.objects.count() == 0
