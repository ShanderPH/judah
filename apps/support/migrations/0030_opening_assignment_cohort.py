"""Persist and protect frozen opening assignment cohorts."""

from __future__ import annotations

import uuid
import warnings

from django.db import migrations, models

TABLE = "opening_assignment_cohorts"
CLIENT_ROLES = ("anon", "authenticated")
RUNTIME_ROLES = ("judah_production_runtime", "judah_staging_runtime")


def protect_cohort_table(_apps, schema_editor) -> None:
    """Apply operational-table RLS and least-privilege runtime grants."""
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.connection.ops.quote_name
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT active_role.rolsuper OR c.relowner = active_role.oid
                   OR pg_has_role(current_user, c.relowner, 'USAGE')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_roles active_role ON active_role.rolname = current_user
            WHERE n.nspname = 'public' AND c.relname = %s
            """,
            [TABLE],
        )
        manageable = cursor.fetchone()
        if not manageable or not manageable[0]:
            warnings.warn(
                f"Operational RLS requires a table-owner connection; skipped: {TABLE}. "
                "Apply the approved Supabase privileged migration separately.",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        cursor.execute("SELECT rolname FROM pg_roles")
        roles = {str(row[0]) for row in cursor.fetchall()}
        table = f"public.{quote(TABLE)}"
        cursor.execute(
            f"COMMENT ON TABLE {table} IS 'JUDAH operational data; direct anon/authenticated access is prohibited.'"
        )
        cursor.execute(
            "COMMENT ON INDEX public.idx_open_cohort_deadline IS "
            "'Supports bounded active-cohort deadline/readiness scans.'"
        )
        for role in CLIENT_ROLES:
            if role in roles:
                cursor.execute(f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {quote(role)}")
        cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        for role in RUNTIME_ROLES:
            if role in roles:
                cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {quote(role)}")


def unprotect_cohort_table(_apps, schema_editor) -> None:
    """Reverse grants before Django drops the cohort table."""
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.connection.ops.quote_name
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles")
        roles = {str(row[0]) for row in cursor.fetchall()}
        table = f"public.{quote(TABLE)}"
        for role in RUNTIME_ROLES:
            if role in roles:
                cursor.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {table} FROM {quote(role)}")
        cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [("support", "0029_grant_helpdesk_calendar_runtime_access")]

    operations = [
        migrations.CreateModel(
            name="OpeningAssignmentCohort",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("window_started_at", models.DateTimeField(unique=True)),
                ("cohort_observed_at", models.DateTimeField()),
                ("recheck_at", models.DateTimeField()),
                ("deadline_at", models.DateTimeField()),
                ("member_agent_ids", models.JSONField(default=list)),
                ("initial_eligible_count", models.PositiveIntegerField()),
                ("initial_stabilizing_count", models.PositiveIntegerField()),
                (
                    "state",
                    models.CharField(
                        choices=[("active", "Active"), ("released", "Released")],
                        default="active",
                        max_length=16,
                    ),
                ),
                (
                    "release_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("all_settled", "All Settled"),
                            ("deadline", "Deadline"),
                            ("disabled", "Disabled"),
                        ],
                        default="",
                        max_length=16,
                    ),
                ),
                ("callback_scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": TABLE},
        ),
        migrations.AddIndex(
            model_name="openingassignmentcohort",
            index=models.Index(fields=["state", "deadline_at"], name="idx_open_cohort_deadline"),
        ),
        migrations.RunPython(protect_cohort_table, unprotect_cohort_table),
    ]
