"""Gate B (BE-02) dual-write tests: proven cycles attach additively.

With ``CONVERSATION_CYCLES_ENFORCED=False`` (the default and only approved
value for this gate), legacy behavior is preserved and cycles are attached
only when the occurrence is provable. With enforcement on, divergences fail
closed before any effect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone

from apps.support.conversation_cycle_service import (
    CycleClassification,
    build_cycle_key,
    open_or_get_cycle,
)
from apps.support.durable_assignment_service import execute_assignment_attempt, reserve_next_assignment
from apps.support.matchmaker_service import enqueue_new_ticket
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    NewConversation,
    SupportConversationCycle,
)

pytestmark = pytest.mark.django_db

PORTAL = "12345678"
TICKET = "T100"
ENTRY_MS = 1_753_000_000_000
ENTRY_AT = datetime.fromtimestamp(ENTRY_MS / 1000, tz=UTC)
LATER_MS = ENTRY_MS + 3_600_000

ELIGIBLE_TICKET = {
    "id": TICKET,
    "pipeline": "636459134",
    "owner_id": "",
    "subject": "Test ticket",
}


def _mock_client(payload: dict | None = None) -> MagicMock:
    client = MagicMock()
    client.get_ticket_details.return_value = payload or dict(ELIGIBLE_TICKET)
    return client


def _persisted_cycle(
    *,
    ticket: str = TICKET,
    account: str = PORTAL,
    entered_ms: int = ENTRY_MS,
    state: str = SupportConversationCycle.State.QUEUED,
) -> SupportConversationCycle:
    entered_at = datetime.fromtimestamp(entered_ms / 1000, tz=UTC)
    return SupportConversationCycle.objects.create(
        cycle_key=build_cycle_key(
            source_system="hubspot",
            source_account_id=account,
            hubspot_ticket_id=ticket,
            entered_stage_at=entered_at,
        ),
        source_account_id=account,
        hubspot_ticket_id=ticket,
        entered_stage_at=entered_at,
        state=state,
        opened_at=entered_at,
    )


class TestDualWriteEnforcementOff:
    @pytest.fixture(autouse=True)
    def _settings(self):
        with override_settings(HUBSPOT_PORTAL_ID=PORTAL, CONVERSATION_CYCLES_ENFORCED=False):
            yield

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_proven_occurrence_opens_and_attaches_cycle(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, ENTRY_MS, source_event_id="event-123")

        assert row is not None
        cycle = SupportConversationCycle.objects.get()
        assert cycle.state == SupportConversationCycle.State.QUEUED
        assert cycle.source_account_id == PORTAL
        assert cycle.entered_stage_at == ENTRY_AT
        assert cycle.opened_at == ENTRY_AT
        assert cycle.source_event_id == "event-123"
        row.refresh_from_db()
        assert row.cycle_id == cycle.pk

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_current_hubspot_property_recovers_missing_payload_timestamp(self, mock_client_fn) -> None:
        payload = dict(ELIGIBLE_TICKET, entered_novo_at=str(ENTRY_MS))
        mock_client_fn.return_value = _mock_client(payload)

        row = enqueue_new_ticket(TICKET, None, source_event_id="event-recovered")

        assert row is not None
        cycle = SupportConversationCycle.objects.get()
        assert cycle.entered_stage_at == ENTRY_AT
        assert cycle.source_event_id == "event-recovered"

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_retry_of_same_occurrence_is_idempotent(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        first = enqueue_new_ticket(TICKET, ENTRY_MS)
        second = enqueue_new_ticket(TICKET, ENTRY_MS)

        assert first is not None and second is not None
        assert first.pk == second.pk
        assert SupportConversationCycle.objects.count() == 1
        assert NewConversation.objects.count() == 1
        second.refresh_from_db()
        assert second.cycle_id == SupportConversationCycle.objects.get().pk

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_existing_cycle_is_attached_without_new_insert(self, mock_client_fn) -> None:
        cycle = _persisted_cycle()
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, ENTRY_MS)

        assert row is not None
        assert SupportConversationCycle.objects.count() == 1
        row.refresh_from_db()
        assert row.cycle_id == cycle.pk

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_cycle_propagates_through_current_assignment_writers(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        queue_row = enqueue_new_ticket(TICKET, ENTRY_MS)
        assert queue_row is not None and queue_row.cycle_id is not None
        agent = Agent.objects.create(
            name="Cycle Agent",
            agent_email="cycle-agent@example.test",
            hubspot_owner_id=7001,
            status_enum=Agent.StatusEnum.ONLINE,
            is_active=True,
            auto_assign_enabled=True,
            max_simultaneous_chats=5,
            availability_observed_at=timezone.now(),
            eligibility_state=Agent.EligibilityState.ELIGIBLE,
            eligibility_reason="eligible",
            availability_revision=1,
        )
        with patch(
            "apps.support.durable_assignment_service._verify_candidates",
            return_value=[(agent, "eligible")],
        ):
            reservation = reserve_next_assignment(TICKET)
        assert reservation.attempt is not None
        assert reservation.attempt.cycle_id == queue_row.cycle_id

        with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
            client_factory.return_value.assign_ticket_owner.return_value = {
                "id": TICKET,
                "owner_id": agent.hubspot_owner_id,
            }
            assert execute_assignment_attempt(reservation.attempt.pk) == "assigned"

        reservation.attempt.refresh_from_db()
        assert reservation.attempt.state == AssignmentAttempt.State.COMPLETED
        assert AssignedConversation.objects.count() == 1
        assert AssignedConversation.objects.get(hubspot_ticket_id=TICKET).cycle_id == queue_row.cycle_id
        assert AssignmentLog.objects.get(assignment_attempt=reservation.attempt).cycle_id == queue_row.cycle_id

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_stale_cycle_aborts_before_hubspot_and_releases_capacity(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        queue_row = enqueue_new_ticket(TICKET, ENTRY_MS)
        assert queue_row is not None and queue_row.cycle_id is not None
        agent = Agent.objects.create(
            name="Stale Cycle Agent",
            agent_email="stale-cycle-agent@example.test",
            hubspot_owner_id=7002,
            status_enum=Agent.StatusEnum.ONLINE,
            is_active=True,
            auto_assign_enabled=True,
            max_simultaneous_chats=5,
            availability_observed_at=timezone.now(),
            eligibility_state=Agent.EligibilityState.ELIGIBLE,
            eligibility_reason="eligible",
            availability_revision=1,
        )
        with patch(
            "apps.support.durable_assignment_service._verify_candidates",
            return_value=[(agent, "eligible")],
        ):
            reservation = reserve_next_assignment(TICKET)
        assert reservation.attempt is not None
        SupportConversationCycle.objects.filter(pk=queue_row.cycle_id).update(
            state=SupportConversationCycle.State.CANCELLED
        )

        with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
            assert execute_assignment_attempt(reservation.attempt.pk) == "skipped_stale_cycle"
            client_factory.return_value.assign_ticket_owner.assert_not_called()

        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 0

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_missing_timestamp_fails_closed_without_fabricated_identity(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, None)

        assert row is None
        assert not SupportConversationCycle.objects.exists()

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_invalid_timestamp_fails_closed_without_fabricated_identity(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, "bogus")

        assert row is None
        assert not SupportConversationCycle.objects.exists()

    @override_settings(HUBSPOT_PORTAL_ID="")
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_missing_portal_preserves_legacy_behavior(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, ENTRY_MS)

        assert row is not None
        assert row.cycle_id is None
        assert not SupportConversationCycle.objects.exists()

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_active_conflict_is_telemetry_only_and_keeps_legacy_flow(self, mock_client_fn) -> None:
        _persisted_cycle(entered_ms=ENTRY_MS, state=SupportConversationCycle.State.ASSIGNED)
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, LATER_MS)

        assert row is not None
        row.refresh_from_db()
        assert row.cycle_id is None
        assert SupportConversationCycle.objects.count() == 1
        # The existing active cycle is never closed or replaced implicitly.
        cycle = SupportConversationCycle.objects.get()
        assert cycle.state == SupportConversationCycle.State.ASSIGNED

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_stale_occurrence_is_telemetry_only(self, mock_client_fn) -> None:
        _persisted_cycle(entered_ms=LATER_MS, state=SupportConversationCycle.State.CLOSED)
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, ENTRY_MS)

        assert row is not None
        assert row.cycle_id is None
        assert SupportConversationCycle.objects.count() == 1


class TestDualWriteEnforced:
    @pytest.fixture(autouse=True)
    def _settings(self):
        with override_settings(HUBSPOT_PORTAL_ID=PORTAL, CONVERSATION_CYCLES_ENFORCED=True):
            yield

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_active_conflict_fails_closed_without_effects(self, mock_client_fn) -> None:
        _persisted_cycle(entered_ms=ENTRY_MS, state=SupportConversationCycle.State.QUEUED)
        client = _mock_client()
        mock_client_fn.return_value = client
        row = enqueue_new_ticket(TICKET, LATER_MS)

        assert row is None
        assert not NewConversation.objects.exists()
        assert SupportConversationCycle.objects.count() == 1
        client.assign_ticket_owner.assert_not_called()

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_missing_timestamp_fails_closed(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        assert enqueue_new_ticket(TICKET, None) is None
        assert not NewConversation.objects.exists()

    @override_settings(HUBSPOT_PORTAL_ID="")
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_missing_portal_fails_closed(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        assert enqueue_new_ticket(TICKET, ENTRY_MS) is None
        assert not NewConversation.objects.exists()

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_proven_occurrence_still_enqueues(self, mock_client_fn) -> None:
        mock_client_fn.return_value = _mock_client()
        row = enqueue_new_ticket(TICKET, ENTRY_MS)

        assert row is not None
        assert SupportConversationCycle.objects.count() == 1


class TestOpenOrGetCycleRaceCapture:
    @pytest.fixture(autouse=True)
    def _settings(self):
        with override_settings(HUBSPOT_PORTAL_ID=PORTAL):
            yield

    def test_integrity_error_race_returns_idempotent_duplicate(self) -> None:
        existing = _persisted_cycle(entered_ms=ENTRY_MS)
        with patch.object(
            SupportConversationCycle.objects,
            "create",
            side_effect=IntegrityError("duplicate natural key"),
        ):
            result = open_or_get_cycle(
                hubspot_ticket_id=TICKET,
                entered_stage_value=ENTRY_MS,
            )
        assert result.admission.classification is CycleClassification.DUPLICATE
        assert result.cycle is not None
        assert result.cycle.pk == existing.pk
        assert SupportConversationCycle.objects.count() == 1

    def test_created_then_same_occurrence_returns_duplicate(self) -> None:
        first = open_or_get_cycle(hubspot_ticket_id=TICKET, entered_stage_value=ENTRY_MS)
        second = open_or_get_cycle(hubspot_ticket_id=TICKET, entered_stage_value=ENTRY_MS)
        assert first.admission.classification is CycleClassification.CREATED
        assert second.admission.classification is CycleClassification.DUPLICATE
        assert first.cycle is not None and second.cycle is not None
        assert first.cycle.pk == second.cycle.pk
