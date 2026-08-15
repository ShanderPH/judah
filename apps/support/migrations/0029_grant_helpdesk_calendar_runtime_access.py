"""Grant JUDAH runtime roles access to the native helpdesk calendar tables."""

from django.db import migrations

CALENDAR_TABLES = (
    "helpdesk_schedules",
    "helpdesk_schedule_rules",
    "helpdesk_schedule_intervals",
    "helpdesk_absence_messages",
)
RUNTIME_ROLES = (
    "judah_production_runtime",
    "judah_staging_runtime",
)
RUNTIME_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"


def _existing_runtime_roles(schema_editor) -> set[str]:
    placeholders = ", ".join(["%s"] * len(RUNTIME_ROLES))
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"SELECT rolname FROM pg_roles WHERE rolname IN ({placeholders})",
            list(RUNTIME_ROLES),
        )
        return {str(row[0]) for row in cursor.fetchall() if str(row[0]) in RUNTIME_ROLES}


def grant_calendar_runtime_access(_apps, schema_editor) -> None:
    """Grant least-privilege CRUD access to existing JUDAH runtime roles."""
    if schema_editor.connection.vendor != "postgresql":
        return

    quote = schema_editor.connection.ops.quote_name
    roles = _existing_runtime_roles(schema_editor)
    with schema_editor.connection.cursor() as cursor:
        for table in CALENDAR_TABLES:
            qualified_table = f"public.{quote(table)}"
            for role in roles:
                cursor.execute(f"GRANT {RUNTIME_PRIVILEGES} ON TABLE {qualified_table} TO {quote(role)}")


def revoke_calendar_runtime_access(_apps, schema_editor) -> None:
    """Reverse only the grants introduced by this migration."""
    if schema_editor.connection.vendor != "postgresql":
        return

    quote = schema_editor.connection.ops.quote_name
    roles = _existing_runtime_roles(schema_editor)
    with schema_editor.connection.cursor() as cursor:
        for table in CALENDAR_TABLES:
            qualified_table = f"public.{quote(table)}"
            for role in roles:
                cursor.execute(f"REVOKE {RUNTIME_PRIVILEGES} ON TABLE {qualified_table} FROM {quote(role)}")


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0028_helpdeskschedule_helpdeskschedulerule_and_more"),
    ]

    operations = [
        migrations.RunPython(grant_calendar_runtime_access, revoke_calendar_runtime_access),
    ]
