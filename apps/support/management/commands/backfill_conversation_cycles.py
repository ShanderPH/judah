"""Backfill legacy support rows with deterministic conversation cycles."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.support.legacy_cycle_backfill import backfill_legacy_cycles


class Command(BaseCommand):
    """Run a bounded, restartable cycle backfill; HubSpot is never called."""

    help = "Backfill conversation cycles with dry-run, cursor, ticket filter, and JSON report."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--after", default="", help="Resume after this ticket ID.")
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--ticket", default="")
        parser.add_argument("--report", default="", help="Optional local JSON report path.")

    def handle(self, *args, **options) -> None:
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        with transaction.atomic():
            report = backfill_legacy_cycles(
                limit=options["limit"], after=options["after"], ticket_id=options["ticket"]
            ).as_dict()
            if options["dry_run"]:
                transaction.set_rollback(True)
        rendered = json.dumps(report, indent=2, sort_keys=True)
        if options["report"]:
            Path(options["report"]).write_text(rendered + "\n", encoding="utf-8")
        self.stdout.write(rendered)
