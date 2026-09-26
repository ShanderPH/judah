"""Bounded replay of durable calculated closed-stage occurrences."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.ai_agents.models import ConversationEvent
from apps.support.availability_runtime import require_routing_writer_authority
from apps.support.conversation_cycle_service import InvalidStageTimestampError, parse_stage_entry_timestamp
from apps.support.owner_reconciliation_service import CapacityObservationConflictError
from apps.support.ticket_close_service import CloseClassification, TicketCloseOccurrence, reconcile_close_occurrence
from common.exceptions import ExternalServiceError


class Command(BaseCommand):
    """Classify without writes by default; explicitly authorized apply uses the live service."""

    help = "Reconcile close occurrences (dry-run unless --apply; no automatic production repair)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare bounded pagination and the explicit mutation switch."""
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args: object, **options: Any) -> None:  # Any: Django management command keyword contract.
        """Replay only persisted calculated stage-entry values, never receipt timestamps."""
        limit, offset = options["limit"], options["offset"]
        if not 1 <= limit <= 1000 or offset < 0:
            raise CommandError("limit must be between 1 and 1000; offset must be nonnegative")
        apply = bool(options["apply"])
        if apply:
            require_routing_writer_authority("reconcile_ticket_closures")
        events = (
            ConversationEvent.objects.filter(
                source="hubspot",
                event_type="ticket_closed",
                payload__propertyName=f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}",
            )
            .select_related("instance")
            .order_by("created_at", "pk")[offset : offset + limit]
        )
        counts = Counter(
            scanned=0,
            applicable_current=0,
            applicable_historical=0,
            duplicate=0,
            reopen_not_materialized=0,
            ambiguous=0,
            provider_unavailable=0,
            applied=0,
        )
        for event in events:
            counts["scanned"] += 1
            try:
                effective_at = parse_stage_entry_timestamp(event.payload.get("propertyValue"))
            except InvalidStageTimestampError:
                counts["ambiguous"] += 1
                continue
            ticket_id = event.instance.hubspot_ticket_id
            if not ticket_id:
                counts["ambiguous"] += 1
                continue
            try:
                result = reconcile_close_occurrence(
                    TicketCloseOccurrence(ticket_id, effective_at, source_event_id=event.source_event_id),
                    dry_run=not apply,
                )
            except ExternalServiceError:
                counts["provider_unavailable"] += 1
                continue
            except CapacityObservationConflictError:
                counts["ambiguous"] += 1
                continue
            if result.classification in {CloseClassification.APPLIED_CURRENT, CloseClassification.APPLIED_HISTORICAL}:
                key = "applicable_current" if result.closes_current_lifecycle else "applicable_historical"
                counts[key] += 1
                counts["applied"] += int(apply)
            elif result.classification in {CloseClassification.DUPLICATE, CloseClassification.REOPEN_NOT_MATERIALIZED}:
                counts[result.classification.value] += 1
            else:
                counts["ambiguous"] += 1
        self.stdout.write(json.dumps(dict(counts), sort_keys=True))
