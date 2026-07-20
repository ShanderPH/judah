"""Run production migrations without mutating the assignment backlog."""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    """Prepare the database before Railway promotes a new API deployment."""

    help = "Apply migrations while preserving the authoritative assignment queue."

    def handle(self, *args: object, **options: object) -> None:
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        had_pending_migrations = bool(executor.migration_plan(targets))

        call_command(
            "migrate",
            interactive=False,
            verbosity=int(options["verbosity"]),
        )

        migration_state = "pending migrations applied" if had_pending_migrations else "no pending migrations"
        self.stdout.write(self.style.SUCCESS(f"{migration_state}; assignment queue preserved."))
