"""Safely inspect or recover one suppressed HubSpot customer turn."""

from __future__ import annotations

import json

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError

from apps.ai_agents.services.recovery import execute_ticket_recovery, inspect_ticket_recovery


class Command(BaseCommand):
    help = "Dry-run (default) or enqueue an audited recovery for exactly one HubSpot ticket."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--ticket-id", required=True)
        parser.add_argument("--operator", required=True)
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Enqueue the verified turn. Without this flag the command is read-only.",
        )

    def handle(self, *args, **options) -> None:
        inspection = async_to_sync(inspect_ticket_recovery)(options["ticket_id"])
        self.stdout.write(json.dumps({"mode": "execute" if options["execute"] else "dry-run", **inspection}, indent=2))
        if not options["execute"]:
            return
        if not inspection["eligible"]:
            raise CommandError(f"Recovery rejected: {', '.join(inspection['reasons'])}")
        result = execute_ticket_recovery(
            inspection=inspection,
            operator=str(options["operator"]).strip(),
        )
        self.stdout.write(self.style.SUCCESS(json.dumps(result)))
