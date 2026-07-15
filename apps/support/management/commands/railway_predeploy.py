"""Run production migrations and safely suppress a stale assignment backlog."""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.support.models import NewConversation


class Command(BaseCommand):
    """Prepare the database before Railway promotes a new API deployment."""

    help = "Apply migrations and suppress the active queue when schema changes were pending."

    def handle(self, *args: object, **options: object) -> None:
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        had_pending_migrations = bool(executor.migration_plan(targets))

        call_command(
            "migrate",
            interactive=False,
            verbosity=int(options["verbosity"]),
        )

        if not had_pending_migrations:
            self.stdout.write("No pending migrations; assignment queue preserved.")
            return

        now = timezone.now()
        cleared = NewConversation.objects.filter(
            queue_status__in=(
                NewConversation.QueueStatus.PENDING,
                NewConversation.QueueStatus.QUEUED,
            )
        ).update(
            queue_status=NewConversation.QueueStatus.FAILED,
            next_assignment_attempt_at=None,
            failure_code="predeploy_queue_cleared",
            failure_message="Suppressed during a deployment with pending migrations.",
            updated_at=now,
        )
        self.stdout.write(self.style.SUCCESS(f"Suppressed {cleared} pre-existing assignment queue item(s)."))
