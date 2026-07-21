"""Domain contract for support conversation cycles (Gate A).

A conversation cycle is one independent attendance of a HubSpot ticket: a
proven entry into the configured NOVO stage opens a cycle, and a terminal
closure ends it. A ticket may accumulate many sequential cycles, but at most
one cycle is active at a time.

This module is the schema-free part of the contract. It owns:

- strict normalization of HubSpot stage-entry timestamps into UTC;
- the deterministic, versioned ``cycle_key`` derived from the external
  identity ``(source_system, source_account_id, hubspot_ticket_id,
  entered_stage_at)``;
- admission classification (``created``, ``duplicate``, ``stale``,
  ``active_conflict``, ``identity_unavailable``, ``repair_required``);
- the state machine for cycle transitions.

Hard rules enforced here:

- Timestamps that are missing, malformed, or not provably HubSpot
  millisecond-epoch values are rejected. ``timezone.now()``, the webhook
  receipt time, or random UUIDs are never used as identity substitutes.
- ``source_event_id`` is audit metadata only; it never identifies a cycle.
- Retry of the same occurrence is an idempotent ``duplicate`` result, never
  a new cycle and never a repeated external effect.
- An older occurrence never alters a newer cycle (``stale``).
- A newer occurrence while another cycle is active is an auditable
  ``active_conflict``; the active cycle is never closed or replaced
  implicitly.
- Terminal states never return to active. A legitimate reopening is a new
  cycle, not a transition.

Gate B added the physical ``support_conversation_cycles`` table and
``open_or_get_cycle()``, which applies the rules above with
``transaction.atomic()`` / ``select_for_update()`` and a natural-key re-read
after ``IntegrityError``. No HubSpot call may happen inside those
transactions. Cycle-aware ingestion of every entrypoint, projection
transitions, closure, and repair belong to Gates C-D. New entrypoints must
not use ``get_or_create(ticket_id)`` as the identity of an attendance.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError, transaction

if TYPE_CHECKING:
    from collections.abc import Iterable

    from apps.support.models import SupportConversationCycle

CYCLE_KEY_VERSION = "v1"
SOURCE_SYSTEM_HUBSPOT = "hubspot"

# Plausibility window for HubSpot millisecond-epoch timestamps. Values outside
# [2000-01-01, 2100-01-01) are rejected: second-based epochs, receipt clocks,
# and corrupted payloads must never become cycle identities.
_MIN_STAGE_ENTRY_MS = 946_684_800_000
_MAX_STAGE_ENTRY_MS = 4_102_444_800_000


class InvalidStageTimestampError(ValueError):
    """Raised when a stage-entry timestamp is absent or not a provable HubSpot ms-epoch value."""


class CycleIdentityUnavailableError(ValueError):
    """Raised when the external identity of a cycle cannot be established."""


class InvalidCycleTransitionError(ValueError):
    """Raised when a cycle state transition violates the contract."""


class CycleState(StrEnum):
    """Lifecycle states of a support conversation cycle."""

    QUEUED = "queued"
    ASSIGNED = "assigned"
    REPAIR_REQUIRED = "repair_required"
    CLOSED = "closed"
    CANCELLED = "cancelled"


ACTIVE_CYCLE_STATES = frozenset(
    {
        CycleState.QUEUED,
        CycleState.ASSIGNED,
        CycleState.REPAIR_REQUIRED,
    }
)
"""States that hold the single active-cycle slot of a ticket."""

TERMINAL_CYCLE_STATES = frozenset(
    {
        CycleState.CLOSED,
        CycleState.CANCELLED,
    }
)
"""States a cycle can never leave. A legitimate reopening is another cycle."""

_ALLOWED_TRANSITIONS = frozenset(
    {
        (CycleState.QUEUED, CycleState.ASSIGNED),
        (CycleState.QUEUED, CycleState.CLOSED),
        (CycleState.QUEUED, CycleState.CANCELLED),
        (CycleState.ASSIGNED, CycleState.CLOSED),
        (CycleState.QUEUED, CycleState.REPAIR_REQUIRED),
        (CycleState.ASSIGNED, CycleState.REPAIR_REQUIRED),
    }
)

_RECONCILIATION_TARGETS = frozenset(
    {
        CycleState.QUEUED,
        CycleState.ASSIGNED,
        CycleState.CLOSED,
        CycleState.CANCELLED,
    }
)


class CycleClassification(StrEnum):
    """Admission outcome for one stage-entry occurrence."""

    CREATED = "created"
    DUPLICATE = "duplicate"
    STALE = "stale"
    ACTIVE_CONFLICT = "active_conflict"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    REPAIR_REQUIRED = "repair_required"


def parse_stage_entry_timestamp(value: str | int | None) -> datetime:
    """Normalize a HubSpot stage-entry timestamp into an aware UTC datetime.

    Args:
        value: Millisecond-epoch value as delivered by HubSpot (string or int).

    Returns:
        The occurrence instant, timezone-aware in UTC.

    Raises:
        InvalidStageTimestampError: If the value is missing, malformed, or
            outside the plausible millisecond-epoch window.
    """
    if value is None:
        raise InvalidStageTimestampError("stage-entry timestamp is absent")
    try:
        milliseconds = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise InvalidStageTimestampError(f"stage-entry timestamp is not numeric: {value!r}") from exc
    if not _MIN_STAGE_ENTRY_MS <= milliseconds < _MAX_STAGE_ENTRY_MS:
        raise InvalidStageTimestampError(f"stage-entry timestamp is outside the plausible ms-epoch window: {value!r}")
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


@dataclass(frozen=True, slots=True)
class CycleIdentity:
    """Immutable external identity of one conversation cycle.

    ``source_event_id`` is deliberately excluded: delivery IDs deduplicate
    webhook transport, they do not identify an attendance.
    """

    source_system: str
    source_account_id: str
    hubspot_ticket_id: str
    entered_stage_at: datetime
    cycle_key: str


def build_cycle_key(
    *,
    source_system: str,
    source_account_id: str,
    hubspot_ticket_id: str,
    entered_stage_at: datetime,
) -> str:
    """Build the versioned, deterministic, log-safe key of a cycle.

    The key is a SHA-256 digest of the canonical natural key, so logs and
    metrics never embed ticket or portal identifiers, and identical
    occurrences always produce identical keys.
    """
    canonical = "|".join(
        (
            source_system,
            source_account_id,
            hubspot_ticket_id,
            entered_stage_at.astimezone(UTC).isoformat(),
        )
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{source_system}:{CYCLE_KEY_VERSION}:{digest}"


def build_cycle_identity(
    *,
    hubspot_ticket_id: str,
    entered_stage_at: datetime,
    source_account_id: str | None = None,
) -> CycleIdentity:
    """Assemble a validated cycle identity from proven occurrence data.

    Args:
        hubspot_ticket_id: HubSpot ticket ID the occurrence belongs to.
        entered_stage_at: Proven stage-entry instant (use
            ``parse_stage_entry_timestamp`` for raw HubSpot values).
        source_account_id: HubSpot portal ID. Defaults to the configured
            ``HUBSPOT_PORTAL_ID``; never assumed silently.

    Returns:
        The immutable identity, including its deterministic ``cycle_key``.

    Raises:
        CycleIdentityUnavailableError: If the portal is not configured, the
            ticket ID is empty, or the timestamp is not a valid instant.
    """
    account = (source_account_id or str(getattr(settings, "HUBSPOT_PORTAL_ID", ""))).strip()
    if not account:
        raise CycleIdentityUnavailableError("HUBSPOT_PORTAL_ID is not configured")
    ticket = str(hubspot_ticket_id).strip()
    if not ticket:
        raise CycleIdentityUnavailableError("hubspot_ticket_id is empty")
    if not isinstance(entered_stage_at, datetime):
        raise CycleIdentityUnavailableError("entered_stage_at is not a datetime")
    entered_utc = entered_stage_at if entered_stage_at.tzinfo else entered_stage_at.replace(tzinfo=UTC)
    entered_utc = entered_utc.astimezone(UTC)
    return CycleIdentity(
        source_system=SOURCE_SYSTEM_HUBSPOT,
        source_account_id=account,
        hubspot_ticket_id=ticket,
        entered_stage_at=entered_utc,
        cycle_key=build_cycle_key(
            source_system=SOURCE_SYSTEM_HUBSPOT,
            source_account_id=account,
            hubspot_ticket_id=ticket,
            entered_stage_at=entered_utc,
        ),
    )


@dataclass(frozen=True, slots=True)
class CycleSnapshot:
    """Minimal view of a persisted cycle, as loaded under lock by the writer.

    Gate B's persistence layer materializes snapshots from the cycle table;
    admission decisions are then made without further I/O.
    """

    cycle_key: str
    entered_stage_at: datetime
    state: CycleState


@dataclass(frozen=True, slots=True)
class CycleAdmission:
    """Explicit result of admitting one stage-entry occurrence."""

    classification: CycleClassification
    identity: CycleIdentity | None
    reason: str


def classify_cycle_admission(
    identity: CycleIdentity,
    existing: Iterable[CycleSnapshot],
) -> CycleAdmission:
    """Classify one proven occurrence against the known cycles of its ticket.

    The decision order is deterministic and fail-closed:

    1. same natural key already persisted -> ``duplicate`` (idempotent retry);
    2. any known cycle with a later entry -> ``stale`` (out-of-order event);
    3. active cycle in ``repair_required`` -> ``repair_required`` (explicit
       reconciliation required before anything new opens);
    4. any other active cycle -> ``active_conflict`` (auditable; never closed
       or replaced implicitly);
    5. otherwise -> ``created``.

    Args:
        identity: Proven identity of the incoming occurrence.
        existing: Snapshots of cycles already known for the same ticket,
            loaded by the caller under the appropriate lock.

    Returns:
        The admission decision; never raises for domain conditions.
    """
    snapshots = list(existing)
    if any(snapshot.cycle_key == identity.cycle_key for snapshot in snapshots):
        return CycleAdmission(CycleClassification.DUPLICATE, identity, "occurrence already persisted")
    if any(snapshot.entered_stage_at > identity.entered_stage_at for snapshot in snapshots):
        return CycleAdmission(CycleClassification.STALE, identity, "a newer cycle is already known")
    actives = [snapshot for snapshot in snapshots if snapshot.state in ACTIVE_CYCLE_STATES]
    if any(snapshot.state == CycleState.REPAIR_REQUIRED for snapshot in actives):
        return CycleAdmission(
            CycleClassification.REPAIR_REQUIRED,
            identity,
            "active cycle awaits explicit reconciliation",
        )
    if actives:
        return CycleAdmission(
            CycleClassification.ACTIVE_CONFLICT,
            identity,
            "ticket already has an active cycle",
        )
    return CycleAdmission(CycleClassification.CREATED, identity, "no active cycle blocks opening")


def admit_cycle_occurrence(
    *,
    hubspot_ticket_id: str,
    entered_stage_value: str | int | None,
    existing: Iterable[CycleSnapshot] = (),
    source_account_id: str | None = None,
    source_event_id: str | None = None,
) -> CycleAdmission:
    """Admit one NOVO-stage occurrence without any I/O or clock access.

    Missing or unprovable identity data yields ``identity_unavailable``
    instead of a fabricated identity. ``source_event_id`` is accepted only to
    be echoed into logs by callers; it never influences the decision.

    Args:
        hubspot_ticket_id: HubSpot ticket ID.
        entered_stage_value: Raw HubSpot ms-epoch stage-entry value.
        existing: Known cycles for the ticket (snapshots loaded under lock).
        source_account_id: Portal override; defaults to settings.
        source_event_id: Audit-only delivery identifier.

    Returns:
        The admission decision with the identity when it could be built.
    """
    del source_event_id  # audit-only metadata; never part of cycle identity
    try:
        entered_stage_at = parse_stage_entry_timestamp(entered_stage_value)
        identity = build_cycle_identity(
            hubspot_ticket_id=hubspot_ticket_id,
            entered_stage_at=entered_stage_at,
            source_account_id=source_account_id,
        )
    except (InvalidStageTimestampError, CycleIdentityUnavailableError) as exc:
        return CycleAdmission(CycleClassification.IDENTITY_UNAVAILABLE, None, str(exc))
    return classify_cycle_admission(identity, existing)


@dataclass(frozen=True, slots=True)
class CycleOpenResult:
    """Outcome of opening (or idempotently returning) a persisted cycle."""

    admission: CycleAdmission
    cycle: SupportConversationCycle | None


def _snapshot_of(row: SupportConversationCycle) -> CycleSnapshot:
    """Project a persisted cycle row into the admission decision view."""
    return CycleSnapshot(
        cycle_key=row.cycle_key,
        entered_stage_at=row.entered_stage_at,
        state=CycleState(row.state),
    )


def open_or_get_cycle(
    *,
    hubspot_ticket_id: str,
    entered_stage_value: str | int | None,
    source_event_id: str | None = None,
    source_account_id: str | None = None,
) -> CycleOpenResult:
    """Open (or idempotently return) the cycle of one NOVO-stage occurrence.

    Orchestrates the Gate A contract against the Gate B table: the proven
    identity is built without clock access, known cycles of the ticket are
    locked with ``select_for_update()`` inside ``transaction.atomic()``, the
    admission decision is made by ``classify_cycle_admission()``, and a new
    row is inserted only on ``created``. A concurrent insert losing the race
    surfaces as ``IntegrityError``; the natural key is then re-read and the
    idempotent ``duplicate`` result is returned, so no effect is repeated.

    This function never calls HubSpot and never mutates owners; callers must
    keep external effects outside of these short transactions.

    Args:
        hubspot_ticket_id: HubSpot ticket ID.
        entered_stage_value: Raw HubSpot ms-epoch stage-entry value.
        source_event_id: Audit-only delivery identifier persisted on creation.
        source_account_id: Portal override; defaults to settings.

    Returns:
        The admission decision plus the cycle row when one exists for the
        occurrence (created now or previously persisted).
    """
    from apps.support.models import SupportConversationCycle

    try:
        entered_stage_at = parse_stage_entry_timestamp(entered_stage_value)
        identity = build_cycle_identity(
            hubspot_ticket_id=hubspot_ticket_id,
            entered_stage_at=entered_stage_at,
            source_account_id=source_account_id,
        )
    except (InvalidStageTimestampError, CycleIdentityUnavailableError) as exc:
        return CycleOpenResult(CycleAdmission(CycleClassification.IDENTITY_UNAVAILABLE, None, str(exc)), None)

    with transaction.atomic():
        locked = list(
            SupportConversationCycle.objects.select_for_update().filter(
                source_account_id=identity.source_account_id,
                hubspot_ticket_id=identity.hubspot_ticket_id,
            )
        )
        admission = classify_cycle_admission(identity, [_snapshot_of(row) for row in locked])
        if admission.classification is not CycleClassification.CREATED:
            by_key = {row.cycle_key: row for row in locked}
            return CycleOpenResult(admission, by_key.get(identity.cycle_key))
        try:
            with transaction.atomic():
                cycle = SupportConversationCycle.objects.create(
                    cycle_key=identity.cycle_key,
                    source_system=identity.source_system,
                    source_account_id=identity.source_account_id,
                    hubspot_ticket_id=identity.hubspot_ticket_id,
                    entered_stage_at=identity.entered_stage_at,
                    source_event_id=source_event_id or "",
                    opened_at=identity.entered_stage_at,
                )
        except IntegrityError:
            cycle = SupportConversationCycle.objects.get(
                source_system=identity.source_system,
                source_account_id=identity.source_account_id,
                hubspot_ticket_id=identity.hubspot_ticket_id,
                entered_stage_at=identity.entered_stage_at,
            )
            admission = CycleAdmission(
                CycleClassification.DUPLICATE,
                identity,
                "concurrent insert persisted the cycle first",
            )
        return CycleOpenResult(admission, cycle)


def transition_cycle_state(
    current: CycleState,
    target: CycleState,
    *,
    reconciliation: bool = False,
) -> CycleState:
    """Validate and apply a cycle state transition.

    Args:
        current: Current persisted state.
        target: Desired state.
        reconciliation: Must be True to leave ``repair_required``; marks an
            explicit human/operator reconciliation, never an automatic flow.

    Returns:
        The target state when the transition is authorized.

    Raises:
        InvalidCycleTransitionError: If the transition is not in the contract
            (including terminal-state exits and same-state no-ops).
    """
    if current in TERMINAL_CYCLE_STATES:
        raise InvalidCycleTransitionError(f"terminal cycle state {current} cannot transition to {target}")
    if current == CycleState.REPAIR_REQUIRED:
        if reconciliation and target in _RECONCILIATION_TARGETS:
            return target
        raise InvalidCycleTransitionError(
            f"repair_required only exits via explicit reconciliation to {sorted(_RECONCILIATION_TARGETS)}"
        )
    if (current, target) in _ALLOWED_TRANSITIONS:
        return target
    raise InvalidCycleTransitionError(f"cycle transition {current} -> {target} is not authorized")
