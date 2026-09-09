"""Explicit, idempotent bootstrap; never invoked by a schema migration."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.support.capacity_service import (
    capacity_count,
    capacity_mode,
    conclude_reservation,
    hold_capacity,
    materialize,
    ticket_transaction,
)
from apps.support.models import Agent, AssignmentAttempt, ConversationReassignment
from apps.support.owner_reconciliation_service import refresh_agent_capacity


def bootstrap_agent(agent: Agent) -> dict[str, int | bool | str]:
    """Import operation evidence conservatively, then confirm ticket identities."""
    imported = 0
    attempts = AssignmentAttempt.objects.filter(selected_agent=agent).exclude(state="completed")
    for attempt in attempts.order_by("pk"):
        with ticket_transaction(attempt.ticket_id) as occupancy:
            locked = AssignmentAttempt.objects.select_for_update().get(pk=attempt.pk)
            target = Agent.objects.select_for_update().get(pk=agent.pk)
            reservation = hold_capacity(occupancy, target, attempt=locked)
            if locked.compensated_at is not None and locked.state in {"retryable", "compensated"}:
                conclude_reservation(reservation, converted=False, reason="bootstrap_release_evidence")
                materialize({target.pk})
            imported += 1
    for intent in ConversationReassignment.objects.filter(to_agent=agent, reassignment_source__endswith=":reserved"):
        with ticket_transaction(intent.hubspot_ticket_id) as occupancy:
            target = Agent.objects.select_for_update().get(pk=agent.pk)
            hold_capacity(occupancy, target, reassignment=intent)
            imported += 1
    ready = refresh_agent_capacity(agent, force=True)
    agent.refresh_from_db()
    return {
        "agent_id": str(agent.pk),
        "operations_inspected": imported,
        "ready": ready,
        "identified_count": capacity_count(agent.pk),
        "legacy_count": agent.current_simultaneous_chats,
    }


class Command(BaseCommand):
    """Prepare shadow evidence without activating the new counter contract."""

    help = "Bootstrap identified capacity in shadow mode; performs provider reads and local operational writes."

    def handle(self, *args: object, **options: Any) -> None:  # Any: Django management command option contract.
        """Run only as an explicit authoritative shadow bootstrap."""
        from apps.support.availability_runtime import require_routing_writer_authority

        require_routing_writer_authority("capacity_reconcile")
        if capacity_mode() != "shadow":
            raise CommandError("Bootstrap requires SUPPORT_CAPACITY_MODE=shadow and an approved writer window")
        reports = [bootstrap_agent(agent) for agent in Agent.objects.exclude(is_active=False).order_by("pk")]
        self.stdout.write(json.dumps({"at": timezone.now().isoformat(), "agents": reports}))
