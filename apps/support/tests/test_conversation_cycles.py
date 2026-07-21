"""Gate A tests for the conversation-cycle domain contract.

These tests are pure unit tests: they require no database rows and perform no
I/O. They prove the identity, timestamp, classification, and transition rules
that Gate B's persistence layer will orchestrate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.test import override_settings

from apps.support.conversation_cycle_service import (
    ACTIVE_CYCLE_STATES,
    TERMINAL_CYCLE_STATES,
    CycleClassification,
    CycleIdentityUnavailableError,
    CycleSnapshot,
    CycleState,
    InvalidCycleTransitionError,
    InvalidStageTimestampError,
    admit_cycle_occurrence,
    build_cycle_identity,
    build_cycle_key,
    classify_cycle_admission,
    parse_stage_entry_timestamp,
    transition_cycle_state,
)

PORTAL = "12345678"
TICKET = "9001"
ENTRY_MS = 1_753_000_000_000  # a plausible HubSpot ms-epoch instant
ENTRY_AT = datetime.fromtimestamp(ENTRY_MS / 1000, tz=UTC)


def _identity(
    ticket: str = TICKET,
    entered_at: datetime = ENTRY_AT,
    account: str = PORTAL,
):
    return build_cycle_identity(
        hubspot_ticket_id=ticket,
        entered_stage_at=entered_at,
        source_account_id=account,
    )


def _snapshot(
    entered_at: datetime = ENTRY_AT,
    state: CycleState = CycleState.QUEUED,
    ticket: str = TICKET,
    account: str = PORTAL,
) -> CycleSnapshot:
    identity = _identity(ticket=ticket, entered_at=entered_at, account=account)
    return CycleSnapshot(
        cycle_key=identity.cycle_key,
        entered_stage_at=entered_at,
        state=state,
    )


class TestParseStageEntryTimestamp:
    def test_valid_ms_string_returns_aware_utc(self) -> None:
        parsed = parse_stage_entry_timestamp(str(ENTRY_MS))
        assert parsed == ENTRY_AT
        assert parsed.tzinfo is UTC

    def test_valid_ms_int(self) -> None:
        assert parse_stage_entry_timestamp(ENTRY_MS) == ENTRY_AT

    def test_none_is_rejected(self) -> None:
        with pytest.raises(InvalidStageTimestampError):
            parse_stage_entry_timestamp(None)

    def test_empty_and_garbage_are_rejected(self) -> None:
        for value in ("", "   ", "not-a-number", "2024-01-01T00:00:00Z"):
            with pytest.raises(InvalidStageTimestampError):
                parse_stage_entry_timestamp(value)

    def test_second_based_epoch_is_rejected(self) -> None:
        with pytest.raises(InvalidStageTimestampError):
            parse_stage_entry_timestamp(ENTRY_MS // 1000)

    def test_out_of_window_values_are_rejected(self) -> None:
        for value in (0, -1, 123, 4_102_444_800_000, 99_999_999_999_999):
            with pytest.raises(InvalidStageTimestampError):
                parse_stage_entry_timestamp(value)


class TestCycleIdentity:
    def test_same_occurrence_produces_same_key(self) -> None:
        first = _identity()
        second = _identity()
        assert first.cycle_key == second.cycle_key
        assert first == second

    def test_distinct_occurrences_produce_distinct_keys(self) -> None:
        later = datetime.fromtimestamp((ENTRY_MS + 60_000) / 1000, tz=UTC)
        assert _identity().cycle_key != _identity(entered_at=later).cycle_key
        assert _identity().cycle_key != _identity(ticket="9002").cycle_key
        assert _identity().cycle_key != _identity(account="87654321").cycle_key

    def test_key_is_versioned_and_log_safe(self) -> None:
        key = _identity().cycle_key
        prefix, version, digest = key.split(":")
        assert prefix == "hubspot"
        assert version == "v1"
        assert len(digest) == 64
        int(digest, 16)  # hex digest
        assert TICKET not in key
        assert PORTAL not in key

    def test_key_matches_direct_builder(self) -> None:
        identity = _identity()
        assert identity.cycle_key == build_cycle_key(
            source_system="hubspot",
            source_account_id=PORTAL,
            hubspot_ticket_id=TICKET,
            entered_stage_at=ENTRY_AT,
        )

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        naive = ENTRY_AT.replace(tzinfo=None)
        assert _identity(entered_at=naive).cycle_key == _identity().cycle_key

    def test_empty_ticket_is_rejected(self) -> None:
        with pytest.raises(CycleIdentityUnavailableError):
            _identity(ticket="  ")

    def test_missing_portal_is_fail_closed(self) -> None:
        with (
            override_settings(HUBSPOT_PORTAL_ID=""),
            pytest.raises(CycleIdentityUnavailableError),
        ):
            build_cycle_identity(hubspot_ticket_id=TICKET, entered_stage_at=ENTRY_AT)

    @override_settings(HUBSPOT_PORTAL_ID=PORTAL)
    def test_portal_defaults_to_settings(self) -> None:
        identity = build_cycle_identity(hubspot_ticket_id=TICKET, entered_stage_at=ENTRY_AT)
        assert identity.source_account_id == PORTAL
        assert identity.cycle_key == _identity().cycle_key

    def test_source_event_id_never_changes_identity(self) -> None:
        admission_a = admit_cycle_occurrence(
            hubspot_ticket_id=TICKET,
            entered_stage_value=ENTRY_MS,
            source_account_id=PORTAL,
            source_event_id="event-aaa",
        )
        admission_b = admit_cycle_occurrence(
            hubspot_ticket_id=TICKET,
            entered_stage_value=ENTRY_MS,
            source_account_id=PORTAL,
            source_event_id="event-bbb",
        )
        assert admission_a.identity is not None
        assert admission_a.identity == admission_b.identity


class TestClassifyCycleAdmission:
    def test_created_when_no_cycles_known(self) -> None:
        admission = classify_cycle_admission(_identity(), [])
        assert admission.classification is CycleClassification.CREATED

    def test_duplicate_for_same_occurrence_regardless_of_state(self) -> None:
        for state in CycleState:
            admission = classify_cycle_admission(_identity(), [_snapshot(state=state)])
            assert admission.classification is CycleClassification.DUPLICATE

    def test_stale_when_a_newer_cycle_is_known(self) -> None:
        newer = datetime.fromtimestamp((ENTRY_MS + 60_000) / 1000, tz=UTC)
        admission = classify_cycle_admission(_identity(), [_snapshot(entered_at=newer)])
        assert admission.classification is CycleClassification.STALE

    def test_stale_beats_active_conflict_for_old_events(self) -> None:
        newer = datetime.fromtimestamp((ENTRY_MS + 60_000) / 1000, tz=UTC)
        admission = classify_cycle_admission(
            _identity(),
            [_snapshot(entered_at=newer, state=CycleState.ASSIGNED)],
        )
        assert admission.classification is CycleClassification.STALE

    def test_active_conflict_for_new_occurrence_with_active_cycle(self) -> None:
        older = datetime.fromtimestamp((ENTRY_MS - 60_000) / 1000, tz=UTC)
        for state in (CycleState.QUEUED, CycleState.ASSIGNED):
            admission = classify_cycle_admission(
                _identity(),
                [_snapshot(entered_at=older, state=state)],
            )
            assert admission.classification is CycleClassification.ACTIVE_CONFLICT

    def test_repair_required_for_new_occurrence_with_broken_cycle(self) -> None:
        older = datetime.fromtimestamp((ENTRY_MS - 60_000) / 1000, tz=UTC)
        admission = classify_cycle_admission(
            _identity(),
            [_snapshot(entered_at=older, state=CycleState.REPAIR_REQUIRED)],
        )
        assert admission.classification is CycleClassification.REPAIR_REQUIRED

    def test_terminal_cycles_do_not_block_reopening(self) -> None:
        older = datetime.fromtimestamp((ENTRY_MS - 60_000) / 1000, tz=UTC)
        for state in TERMINAL_CYCLE_STATES:
            admission = classify_cycle_admission(
                _identity(),
                [_snapshot(entered_at=older, state=state)],
            )
            assert admission.classification is CycleClassification.CREATED

    def test_active_states_cover_every_non_terminal_state(self) -> None:
        assert frozenset(CycleState) == ACTIVE_CYCLE_STATES | TERMINAL_CYCLE_STATES
        assert not (ACTIVE_CYCLE_STATES & TERMINAL_CYCLE_STATES)


class TestAdmitCycleOccurrence:
    def test_missing_timestamp_is_identity_unavailable(self) -> None:
        admission = admit_cycle_occurrence(
            hubspot_ticket_id=TICKET,
            entered_stage_value=None,
            source_account_id=PORTAL,
        )
        assert admission.classification is CycleClassification.IDENTITY_UNAVAILABLE
        assert admission.identity is None

    def test_invalid_timestamp_is_identity_unavailable(self) -> None:
        admission = admit_cycle_occurrence(
            hubspot_ticket_id=TICKET,
            entered_stage_value="bogus",
            source_account_id=PORTAL,
        )
        assert admission.classification is CycleClassification.IDENTITY_UNAVAILABLE

    @override_settings(HUBSPOT_PORTAL_ID="")
    def test_missing_portal_is_identity_unavailable(self) -> None:
        admission = admit_cycle_occurrence(
            hubspot_ticket_id=TICKET,
            entered_stage_value=ENTRY_MS,
        )
        assert admission.classification is CycleClassification.IDENTITY_UNAVAILABLE
        assert admission.identity is None

    def test_retry_of_same_occurrence_is_idempotent_duplicate(self) -> None:
        first = admit_cycle_occurrence(
            hubspot_ticket_id=TICKET,
            entered_stage_value=ENTRY_MS,
            source_account_id=PORTAL,
        )
        assert first.classification is CycleClassification.CREATED
        assert first.identity is not None
        persisted = CycleSnapshot(
            cycle_key=first.identity.cycle_key,
            entered_stage_at=first.identity.entered_stage_at,
            state=CycleState.QUEUED,
        )
        retry = admit_cycle_occurrence(
            hubspot_ticket_id=TICKET,
            entered_stage_value=ENTRY_MS,
            existing=[persisted],
            source_account_id=PORTAL,
        )
        assert retry.classification is CycleClassification.DUPLICATE
        assert retry.identity == first.identity


class TestTransitionCycleState:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (CycleState.QUEUED, CycleState.ASSIGNED),
            (CycleState.QUEUED, CycleState.CLOSED),
            (CycleState.QUEUED, CycleState.CANCELLED),
            (CycleState.ASSIGNED, CycleState.CLOSED),
            (CycleState.QUEUED, CycleState.REPAIR_REQUIRED),
            (CycleState.ASSIGNED, CycleState.REPAIR_REQUIRED),
        ],
    )
    def test_authorized_transitions(self, current: CycleState, target: CycleState) -> None:
        assert transition_cycle_state(current, target) is target

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (CycleState.QUEUED, CycleState.QUEUED),
            (CycleState.ASSIGNED, CycleState.ASSIGNED),
            (CycleState.ASSIGNED, CycleState.QUEUED),
            (CycleState.ASSIGNED, CycleState.CANCELLED),
        ],
    )
    def test_unauthorized_transitions_raise(self, current: CycleState, target: CycleState) -> None:
        with pytest.raises(InvalidCycleTransitionError):
            transition_cycle_state(current, target)

    @pytest.mark.parametrize("terminal", sorted(TERMINAL_CYCLE_STATES))
    def test_terminal_states_never_transition(self, terminal: CycleState) -> None:
        for target in CycleState:
            with pytest.raises(InvalidCycleTransitionError):
                transition_cycle_state(terminal, target, reconciliation=True)

    def test_repair_required_requires_explicit_reconciliation(self) -> None:
        for target in CycleState:
            with pytest.raises(InvalidCycleTransitionError):
                transition_cycle_state(CycleState.REPAIR_REQUIRED, target)

    @pytest.mark.parametrize(
        "target",
        [CycleState.QUEUED, CycleState.ASSIGNED, CycleState.CLOSED, CycleState.CANCELLED],
    )
    def test_repair_required_exits_only_via_reconciliation(self, target: CycleState) -> None:
        assert transition_cycle_state(CycleState.REPAIR_REQUIRED, target, reconciliation=True) is target

    def test_repair_required_cannot_reenter_itself(self) -> None:
        with pytest.raises(InvalidCycleTransitionError):
            transition_cycle_state(
                CycleState.REPAIR_REQUIRED,
                CycleState.REPAIR_REQUIRED,
                reconciliation=True,
            )
