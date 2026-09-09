"""Conservative provider observations shared by owner events and scans."""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

import structlog
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.support.capacity_service import (
    capacity_account,
    capacity_enforced,
    capacity_mode,
    conclude_reservation,
    degrade_agents,
    materialize,
    ticket_transaction,
)
from apps.support.models import (
    Agent,
    AgentCapacityReservation,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    ConversationReassignment,
    NewConversation,
    SupportConversationCycle,
    SupportTicketOccupancy,
)

logger = structlog.get_logger(__name__)


class CapacityObservationConflictError(RuntimeError):
    """The read cannot safely supersede locally committed evidence."""


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else None
    if isinstance(value, str):
        parsed = parse_datetime(value)
        return parsed if parsed is not None and timezone.is_aware(parsed) else None
    return None


def _project_owner(row: SupportTicketOccupancy) -> set[UUID]:
    """Update only proven cycle projections; never synthesize attendance time."""
    assigned = AssignedConversation.objects.select_for_update().filter(hubspot_ticket_id=row.hubspot_ticket_id).first()
    affected = {assigned.agent_id} if assigned is not None and assigned.agent_id else set()
    if row.state != "active":
        if row.state == "unassigned" and assigned:
            ConversationReassignment.objects.create(
                hubspot_ticket_id=row.hubspot_ticket_id,
                cycle=assigned.cycle,
                from_agent=assigned.agent,
                from_hubspot_owner_id=assigned.hubspot_owner_id,
                reassigned_at=timezone.now(),
                reassignment_source="hubspot_owner_removed",
            )
            assigned.delete()
        return affected
    cycle = SupportConversationCycle.objects.filter(
        hubspot_ticket_id=row.hubspot_ticket_id,
        source_account_id=row.source_account_id,
        state__in=["queued", "assigned"],
    ).first()
    row.cycle = cycle
    if assigned is not None and assigned.cycle_id is not None and (cycle is None or assigned.cycle_id != cycle.pk):
        logger.warning("capacity_projection_cycle_mismatch", ticket_id=row.hubspot_ticket_id)
        return affected
    if assigned and assigned.hubspot_owner_id != row.hubspot_owner_id:
        old_owner, old_agent = assigned.hubspot_owner_id, assigned.agent
        assigned.agent = row.agent
        assigned.hubspot_owner_id = row.hubspot_owner_id
        assigned.agent_name = row.agent.name if row.agent else ""
        assigned.assignment_count += 1
        assigned.save(update_fields=["agent", "hubspot_owner_id", "agent_name", "assignment_count", "updated_at"])
        # An administrative intention is itself the transfer audit row.
        if not AgentCapacityReservation.objects.filter(
            occupancy=row, state="held", reassignment__isnull=False, agent_id=row.agent_id
        ).exists():
            ConversationReassignment.objects.create(
                hubspot_ticket_id=row.hubspot_ticket_id,
                cycle=assigned.cycle,
                from_agent=old_agent,
                from_hubspot_owner_id=old_owner,
                to_agent=row.agent,
                to_hubspot_owner_id=row.hubspot_owner_id,
                reassigned_at=timezone.now(),
                reassignment_source="hubspot_webhook",
            )
    elif assigned is None and cycle is not None and cycle.state == "queued":
        queue = NewConversation.objects.filter(cycle=cycle).first()
        allowed = queue is not None and (
            queue.queue_status in {"pending", "queued"}
            or (queue.queue_status == "failed" and queue.failure_code == "hubspot_manual_owner_observed")
        )
        if allowed and queue is not None:
            # A reserved automatic/manual attempt is finalized by its own protocol.
            if AgentCapacityReservation.objects.filter(
                occupancy=row,
                state__in=["held", "converted"],
                assignment_attempt__state__in=["reserved", "external_applied", "repair_required"],
                agent_id=row.agent_id,
            ).exists():
                return affected
            AssignedConversation.objects.create(
                hubspot_ticket_id=row.hubspot_ticket_id,
                cycle=cycle,
                agent=row.agent,
                hubspot_owner_id=row.hubspot_owner_id,
                agent_name=row.agent.name if row.agent else "",
                pipeline_id=row.pipeline_id,
                entered_queue_at=queue.entered_queue_at,
                assigned_at=timezone.now(),
            )
            AssignmentLog.objects.create(
                ticket_id=row.hubspot_ticket_id,
                cycle=cycle,
                agent=row.agent,
                hubspot_owner_id=row.hubspot_owner_id,
                agent_name=row.agent.name if row.agent else "",
                assignment_type="manual",
                assigned_by="hubspot_manual",
                pipeline_id=row.pipeline_id,
                entered_queue_at=queue.entered_queue_at,
            )
            cycle.state = "assigned"
            cycle.save(update_fields=["state", "updated_at"])
            queue.delete()
    return affected


def reconcile_ticket(
    ticket_id: str,
    *,
    source: str = "webhook",
    observation_id: str = "",
    revision_tracker: dict[UUID, int] | None = None,
    snapshot: dict[str, object] | None = None,
) -> SupportTicketOccupancy:
    """Read outside locks and apply only if the captured revision still holds."""
    from apps.integrations.hubspot.client import STAGE_FECHADO_ID, SUPPORT_PIPELINE_ID, get_hubspot_client

    with ticket_transaction(ticket_id) as captured:
        revision = captured.revision
        affected = {captured.agent_id} if captured.agent_id else set()
        affected.update(
            AgentCapacityReservation.objects.filter(occupancy=captured, state="held").values_list("agent_id", flat=True)
        )
    try:
        data = get_hubspot_client().get_ticket_details(ticket_id)
        if str(data.get("id")) != ticket_id or not data.get("pipeline") or not data.get("stage"):
            raise CapacityObservationConflictError("Incomplete provider ticket")
        raw_owner = data.get("owner_id")
        if raw_owner and not str(raw_owner).isdigit():
            raise CapacityObservationConflictError("Invalid owner identity")
        owner = int(str(raw_owner)) if raw_owner else None
        updated = _timestamp(data.get("updated_at"))
        with ticket_transaction(ticket_id) as row:
            if row.agent_id:
                affected.add(row.agent_id)
            observed_agent = Agent.objects.filter(hubspot_owner_id=owner).first() if owner else None
            if observed_agent is not None:
                affected.add(observed_agent.pk)
            if row.revision != revision:
                raise CapacityObservationConflictError("Ticket revision changed during provider read")
            if row.provider_updated_at is not None and (updated is None or updated < row.provider_updated_at):
                raise CapacityObservationConflictError("Provider observation predates local confirmation")
            if (
                row.provider_updated_at is not None
                and updated == row.provider_updated_at
                and row.hubspot_owner_id != owner
            ):
                raise CapacityObservationConflictError("Conflicting owners have the same provider revision")
            previous_owner = row.hubspot_owner_id
            row.hubspot_owner_id = owner
            row.agent = observed_agent
            if row.agent_id:
                affected.add(row.agent_id)
            row.pipeline_id = str(data["pipeline"])
            row.state = (
                "out_of_scope"
                if row.pipeline_id != SUPPORT_PIPELINE_ID
                else "closed"
                if data.get("archived") is True or data["stage"] == STAGE_FECHADO_ID
                else "active"
                if owner is not None
                else "unassigned"
            )
            if capacity_enforced():
                project_cycle = True
                if row.state == "active" and data.get("entered_novo_at"):
                    from apps.support.conversation_cycle_service import open_or_get_cycle

                    opened = open_or_get_cycle(
                        hubspot_ticket_id=ticket_id,
                        entered_stage_value=data["entered_novo_at"],
                        source_account_id=row.source_account_id,
                    )
                    project_cycle = (
                        opened.admission.classification in {"created", "duplicate"}
                        and opened.cycle is not None
                        and opened.cycle.state in {"queued", "assigned"}
                    )
                    if opened.cycle is not None and opened.cycle.state == "queued":
                        NewConversation.objects.get_or_create(
                            cycle=opened.cycle,
                            defaults={
                                "hubspot_ticket_id": ticket_id,
                                "pipeline_id": row.pipeline_id,
                                "entered_queue_at": opened.cycle.entered_stage_at,
                                "automatic_assignment_eligible": False,
                            },
                        )
                if project_cycle:
                    affected.update(_project_owner(row))
                else:
                    row.cycle = None
                    affected.update(
                        AssignedConversation.objects.filter(hubspot_ticket_id=ticket_id)
                        .exclude(agent_id__isnull=True)
                        .values_list("agent_id", flat=True)
                    )
                    logger.warning("capacity_projection_cycle_identity_unresolved", ticket_id=ticket_id)
                if row.state == "closed" and data.get("entered_closed_at"):
                    from apps.support.auto_assign_service import _apply_ticket_closed

                    _apply_ticket_closed(ticket_id, data["entered_closed_at"])
            for reservation in AgentCapacityReservation.objects.select_for_update().filter(occupancy=row, state="held"):
                affected.add(reservation.agent_id)
                # Only matching confirmation resolves an in-flight effect. A different
                # owner can still be followed by a concurrently executing PATCH.
                if row.state == "active" and reservation.agent.hubspot_owner_id == owner:
                    conclude_reservation(reservation, converted=True, reason="confirmed_owner")
                elif row.state in {"closed", "out_of_scope"}:
                    conclude_reservation(reservation, converted=False, reason="confirmed_terminal_scope")
            row.revision += 1
            row.provider_updated_at = updated
            row.observed_at = timezone.now()
            row.observation_source = source[:64]
            row.observation_id = observation_id[:128]
            row.save()
            materialize(affected)
            if revision_tracker is not None:
                for identity in affected.intersection(revision_tracker):
                    revision_tracker[identity] += 1
            if snapshot is not None:
                snapshot.update(data)
            if capacity_enforced() and row.state == "active" and row.agent_id and previous_owner != owner:
                Agent.objects.filter(pk=row.agent_id).update(last_assignment_at=timezone.now())
            return row
    except Exception:
        degrade_agents(affected)
        raise


def refresh_agent_capacity(agent: Agent, *, force: bool = False) -> bool:
    """Reconcile a bounded complete portfolio, preserving held reservations."""
    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.support.availability_runtime import require_routing_writer_authority
    from apps.support.owned_cache_lock import OwnedCacheLock

    if capacity_mode() == "off":
        return True
    require_routing_writer_authority("capacity_reconcile")
    agent.refresh_from_db()
    freshness = int(settings.SUPPORT_CAPACITY_FRESHNESS_SECONDS)
    if (
        not force
        and agent.capacity_state == "ready"
        and agent.capacity_reconciled_at is not None
        and (timezone.now() - agent.capacity_reconciled_at).total_seconds() < freshness
    ):
        return True
    lock = OwnedCacheLock(f"capacity-refresh:{capacity_account()}:{agent.pk}", timeout=120)
    if not lock.acquire():
        return False
    try:
        revision_tracker = {agent.pk: agent.capacity_revision}
        scan_started_at = timezone.now()
        deadline = time.monotonic() + 20
        ids, complete = get_hubspot_client().list_active_ticket_ids_by_owner(agent.hubspot_owner_id)
        if not complete:
            raise CapacityObservationConflictError("Incomplete portfolio discovery")
        local_ids = set(SupportTicketOccupancy.objects.filter(agent=agent).values_list("hubspot_ticket_id", flat=True))
        local_ids.update(AssignedConversation.objects.filter(agent=agent).values_list("hubspot_ticket_id", flat=True))
        local_ids.update(
            AgentCapacityReservation.objects.filter(agent=agent, state="held").values_list(
                "occupancy__hubspot_ticket_id", flat=True
            )
        )
        identities = local_ids | set(ids)
        if len(identities) > int(settings.SUPPORT_CAPACITY_MAX_SCAN_TICKETS):
            raise CapacityObservationConflictError("Portfolio exceeds read budget")
        for identity in sorted(identities):
            if time.monotonic() >= deadline:
                raise CapacityObservationConflictError("Portfolio exceeds time budget")
            reconcile_ticket(identity, source="portfolio", revision_tracker=revision_tracker)
        # Pre-activation operations cannot be inferred from LIVE_STATES alone.
        unresolved = (
            AssignmentAttempt.objects.filter(selected_agent=agent)
            .exclude(
                state__in=["completed", "compensated"],
            )
            .exclude(agentcapacityreservation__isnull=False)
            .exists()
        )
        if unresolved:
            raise CapacityObservationConflictError("Legacy operation requires bootstrap classification")
        if (
            AgentCapacityReservation.objects.filter(agent=agent, state="held")
            .filter(Q(assignment_attempt__state="repair_required") | Q(reassignment__isnull=False))
            .exists()
        ):
            raise CapacityObservationConflictError("Ambiguous reservation requires readback")
        with transaction.atomic():
            locked = Agent.objects.select_for_update().get(pk=agent.pk)
            if locked.capacity_revision != revision_tracker[agent.pk]:
                raise CapacityObservationConflictError("Portfolio generation changed during scan")
            locked.capacity_state = "ready"
            locked.capacity_reconciled_at = scan_started_at
            locked.save(update_fields=["capacity_state", "capacity_reconciled_at"])
        agent.refresh_from_db()
        return True
    except Exception as exc:
        degrade_agents({agent.pk})
        logger.warning("capacity_refresh_degraded", agent_id=str(agent.pk), reason=type(exc).__name__)
        return False
    finally:
        lock.release()
