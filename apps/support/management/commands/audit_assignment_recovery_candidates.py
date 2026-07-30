"""Classify missed NOVO assignment candidates without mutating state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime


class Command(BaseCommand):
    """Produce a read-only recovery report for calculated NOVO events."""

    help = "Audit possible assignment misses since an ISO-8601 timestamp; never enqueue or mutate."

    def add_arguments(self, parser) -> None:
        """Register bounded, explicit audit inputs."""
        parser.add_argument("--since", required=True, help="Inclusive ISO-8601 timestamp.")
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args: object, **options: object) -> None:
        """Fetch current provider state and print deterministic classifications."""
        del args
        since = self._parse_since(str(options["since"]))
        limit = max(1, min(int(options["limit"]), 5000))
        report = self._classify(since=since, limit=limit)
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    @staticmethod
    def _parse_since(raw: str) -> datetime:
        parsed = parse_datetime(raw)
        if parsed is None or parsed.tzinfo is None:
            raise CommandError("--since must be a timezone-aware ISO-8601 timestamp.")
        return parsed

    @staticmethod
    def _classify(*, since: datetime, limit: int) -> dict[str, Any]:
        from apps.integrations.hubspot.client import get_hubspot_client
        from apps.support.models import AssignmentAttempt, SupportConversationCycle
        from apps.webhooks.models import WebhookEvent

        property_name = f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_NEW_STAGE_ID}"
        events = WebhookEvent.objects.filter(
            event_type="ticket.propertyChange",
            property_name=property_name,
            created_at__gte=since,
        ).order_by("created_at", "pk")[:limit]
        client = get_hubspot_client()
        candidates: list[dict[str, str]] = []
        counts: dict[str, int] = {}
        seen: set[str] = set()
        for event in events:
            ticket_id = str(event.object_id)
            if ticket_id in seen:
                continue
            seen.add(ticket_id)
            cycle_exists = SupportConversationCycle.objects.filter(
                hubspot_ticket_id=ticket_id,
            ).exists()
            attempt_exists = AssignmentAttempt.objects.filter(ticket_id=ticket_id).exists()
            if cycle_exists or attempt_exists:
                classification = "cycle_or_attempt_exists"
            else:
                try:
                    ticket = client.get_ticket_details(ticket_id)
                except Exception:
                    classification = "ambiguous_quarantine"
                else:
                    owner_id = str(ticket.get("hubspot_owner_id") or ticket.get("owner_id") or "").strip()
                    stage_id = str(ticket.get("hs_pipeline_stage") or ticket.get("pipeline_stage") or "")
                    pipeline_id = str(ticket.get("pipeline") or "")
                    if owner_id:
                        classification = "assigned_elsewhere"
                    elif pipeline_id == str(settings.HUBSPOT_SUPPORT_PIPELINE_ID) and stage_id == str(
                        settings.HUBSPOT_SUPPORT_NEW_STAGE_ID
                    ):
                        classification = "still_new_without_owner"
                    else:
                        classification = "left_new_stage"
            counts[classification] = counts.get(classification, 0) + 1
            candidates.append(
                {
                    "ticket_id": ticket_id,
                    "source_event_id": str(event.event_id or event.pk),
                    "classification": classification,
                }
            )
        return {
            "mode": "read_only",
            "since": since.isoformat(),
            "limit": limit,
            "counts": counts,
            "candidates": candidates,
        }
