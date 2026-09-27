"""Bounded replay of durable calculated closed-stage occurrences."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Min, Q

from apps.ai_agents.models import ConversationEvent
from apps.support.availability_runtime import require_routing_writer_authority
from apps.support.conversation_cycle_service import InvalidStageTimestampError, parse_stage_entry_timestamp
from apps.support.models import SupportConversationCycle
from apps.support.owner_reconciliation_service import CapacityObservationConflictError
from apps.support.ticket_close_service import (
    CloseClassification,
    TicketCloseOccurrence,
    reconcile_close_occurrence,
    resolve_close_target,
)
from common.exceptions import ExternalServiceError


class Command(BaseCommand):
    """Classify cycle-era closures without writes unless --apply is explicit."""

    help = (
        "Reconcile only close occurrences with a temporally matching local cycle (dry-run unless --apply). "
        "The cutoff is the earliest SupportConversationCycle.created_at; --offset counts only matching occurrences. "
        "Skipped counters include events examined before this page fills and may repeat at later offsets."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare bounded pagination and the explicit mutation switch."""
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args: object, **options: Any) -> None:  # Any: Django management command keyword contract.
        """Page proven local-cycle occurrences; leave all other raw events untouched."""
        limit, offset = options["limit"], options["offset"]
        if not 1 <= limit <= 1000 or offset < 0:
            raise CommandError("limit must be between 1 and 1000; offset must be nonnegative")
        apply = bool(options["apply"])
        if apply:
            require_routing_writer_authority("reconcile_ticket_closures")
        cutoff = SupportConversationCycle.objects.aggregate(first_created_at=Min("created_at"))["first_created_at"]
        if cutoff is None:
            raise CommandError("No SupportConversationCycle exists; cycle-era cutoff is unavailable.")
        close_events = ConversationEvent.objects.filter(
            source="hubspot",
            event_type="ticket_closed",
            payload__propertyName=f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}",
        )
        legacy_skipped = close_events.filter(created_at__lt=cutoff).count()
        events = close_events.filter(created_at__gte=cutoff).select_related("instance").order_by("created_at", "pk")
        counts = Counter(
            scanned=0,
            legacy_skipped=legacy_skipped,
            applicable_current=0,
            applicable_historical=0,
            duplicate=0,
            reopen_not_materialized=0,
            no_cycle=0,
            identity_unavailable=0,
            conflict=0,
            ambiguous=0,
            provider_unavailable=0,
            applied=0,
        )
        eligible_seen = 0
        last_created_at = None
        last_pk = None
        while True:
            page = events
            if last_created_at is not None:
                page = page.filter(Q(created_at__gt=last_created_at) | Q(created_at=last_created_at, pk__gt=last_pk))
            batch = list(page[:200])
            if not batch:
                break
            last_created_at, last_pk = batch[-1].created_at, batch[-1].pk
            ticket_ids = {event.instance.hubspot_ticket_id for event in batch if event.instance.hubspot_ticket_id}
            cycles_by_ticket = defaultdict(list)
            for cycle in SupportConversationCycle.objects.filter(hubspot_ticket_id__in=ticket_ids):
                cycles_by_ticket[cycle.hubspot_ticket_id].append(cycle)
            for event in batch:
                try:
                    effective_at = parse_stage_entry_timestamp(event.payload.get("propertyValue"))
                except InvalidStageTimestampError:
                    counts["identity_unavailable"] += 1
                    continue
                if effective_at < cutoff:
                    counts["legacy_skipped"] += 1
                    continue
                ticket_id = event.instance.hubspot_ticket_id
                if not ticket_id:
                    counts["identity_unavailable"] += 1
                    continue
                occurrence = TicketCloseOccurrence(ticket_id, effective_at, source_event_id=event.source_event_id)
                target = resolve_close_target(cycles_by_ticket[ticket_id], occurrence)
                if target.classification in {CloseClassification.NO_CYCLE, CloseClassification.IDENTITY_UNAVAILABLE}:
                    counts[target.classification.value] += 1
                    continue
                eligible_seen += 1
                if eligible_seen <= offset:
                    continue
                counts["scanned"] += 1
                try:
                    result = reconcile_close_occurrence(occurrence, dry_run=not apply)
                except ExternalServiceError:
                    counts["provider_unavailable"] += 1
                except CapacityObservationConflictError:
                    counts["conflict"] += 1
                else:
                    if result.classification in {
                        CloseClassification.APPLIED_CURRENT,
                        CloseClassification.APPLIED_HISTORICAL,
                    }:
                        key = "applicable_current" if result.closes_current_lifecycle else "applicable_historical"
                        counts[key] += 1
                        counts["applied"] += int(apply)
                    elif result.classification in {
                        CloseClassification.DUPLICATE,
                        CloseClassification.REOPEN_NOT_MATERIALIZED,
                        CloseClassification.NO_CYCLE,
                        CloseClassification.IDENTITY_UNAVAILABLE,
                        CloseClassification.CONFLICT,
                        CloseClassification.PROVIDER_UNAVAILABLE,
                    }:
                        counts[result.classification.value] += 1
                    else:
                        counts["ambiguous"] += 1
                if counts["scanned"] == limit:
                    break
            if counts["scanned"] == limit:
                break
        self.stdout.write(json.dumps(dict(counts), sort_keys=True))
        if counts["provider_unavailable"]:
            raise CommandError("Provider unavailable; batch incomplete. Repeat this offset.")
