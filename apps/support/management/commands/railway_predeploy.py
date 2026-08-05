"""Run production migrations without mutating the assignment backlog."""

from __future__ import annotations

import os

import dj_database_url
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

SCHEMA_DATABASE_URL_ENV = "JUDAH_SCHEMA_DATABASE_URL"


def configure_schema_migration_database() -> bool:
    """Use the optional privileged database URL for release migrations.

    Railway runtime credentials intentionally do not own the ``public``
    schema.  Keeping a separate migration URL prevents a release migration
    from being coupled to the application role while leaving all API/worker
    traffic on the normal ``DATABASE_URL``.
    """
    schema_database_url = os.environ.get(SCHEMA_DATABASE_URL_ENV, "").strip()
    if not schema_database_url:
        return False

    schema_database = dj_database_url.parse(schema_database_url, conn_max_age=0)
    connection.close()
    settings.DATABASES["default"].update(schema_database)
    return True


class Command(BaseCommand):
    """Prepare the database before Railway promotes a new API deployment."""

    help = "Apply migrations while preserving the authoritative assignment queue."

    def handle(self, *args: object, **options: object) -> None:
        using_schema_database = configure_schema_migration_database()
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        had_pending_migrations = bool(executor.migration_plan(targets))

        call_command(
            "migrate",
            interactive=False,
            verbosity=int(options["verbosity"]),
        )

        migration_state = "pending migrations applied" if had_pending_migrations else "no pending migrations"
        connection_state = " via dedicated schema URL" if using_schema_database else ""
        self.stdout.write(self.style.SUCCESS(f"{migration_state}{connection_state}; assignment queue preserved."))
