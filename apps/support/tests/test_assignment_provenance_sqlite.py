"""SQLite regression for the assignment provenance CHECK migration."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor

from apps.support.models import AssignmentLog

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "sqlite", reason="SQLite required"),
]


def _support_apps_at(migration_name: str):
    """Return the historical support app registry at one migration node."""
    executor = MigrationExecutor(connection)
    return executor.loader.project_state([("support", migration_name)]).apps


def test_sqlite_assignment_log_check_forward_and_reverse() -> None:
    """SQLite rebuilds must physically remove and recreate the provenance CHECK."""
    migration = import_module("apps.support.migrations.0036_assignment_log_provenance_check")
    before_apps = _support_apps_at("0035_alter_assignedconversation_assigned_at")
    after_apps = _support_apps_at("0036_assignment_log_provenance_check")

    with connection.schema_editor(atomic=False) as schema_editor:
        migration.restore_legacy_check(after_apps, schema_editor)

    unconstrained = AssignmentLog.objects.create(
        ticket_id="sqlite-after-reverse",
        agent_name="Agent",
        assignment_type="invented",
    )
    unconstrained.delete()

    with connection.schema_editor(atomic=False) as schema_editor:
        migration.replace_check(before_apps, schema_editor)

    canonical = AssignmentLog.objects.create(
        ticket_id="sqlite-canonical",
        agent_name="Agent",
        assignment_type="unknown_external",
    )
    canonical.delete()

    with pytest.raises(IntegrityError):
        AssignmentLog.objects.create(
            ticket_id="sqlite-invalid",
            agent_name="Agent",
            assignment_type="invented",
        )
