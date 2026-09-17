"""Grant JUDAH runtime roles access to conversation attendant history."""

from django.db import migrations

ATTENDANT_TABLE = "conversation_instance_attendants"
RUNTIME_ROLES = (
    "judah_production_runtime",
    "judah_staging_runtime",
)
RUNTIME_PRIVILEGES = "SELECT, INSERT, UPDATE"


def _existing_runtime_roles(schema_editor) -> set[str]:
    """Return only configured runtime roles that exist in PostgreSQL."""
    placeholders = ", ".join(["%s"] * len(RUNTIME_ROLES))
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"SELECT rolname FROM pg_roles WHERE rolname IN ({placeholders})",  # nosec B608: fixed placeholder count.
            list(RUNTIME_ROLES),
        )
        return {str(row[0]) for row in cursor.fetchall() if str(row[0]) in RUNTIME_ROLES}


def grant_attendant_runtime_access(_apps, schema_editor) -> None:
    """Grant the minimum privileges required by attendant get-or-create."""
    if schema_editor.connection.vendor != "postgresql":
        return

    quote = schema_editor.connection.ops.quote_name
    qualified_table = f"public.{quote(ATTENDANT_TABLE)}"
    with schema_editor.connection.cursor() as cursor:
        for role in sorted(_existing_runtime_roles(schema_editor)):
            cursor.execute(f"GRANT {RUNTIME_PRIVILEGES} ON TABLE {qualified_table} TO {quote(role)}")


def revoke_attendant_runtime_access(_apps, schema_editor) -> None:
    """Reverse only the privileges introduced by this migration."""
    if schema_editor.connection.vendor != "postgresql":
        return

    quote = schema_editor.connection.ops.quote_name
    qualified_table = f"public.{quote(ATTENDANT_TABLE)}"
    with schema_editor.connection.cursor() as cursor:
        for role in sorted(_existing_runtime_roles(schema_editor)):
            cursor.execute(f"REVOKE {RUNTIME_PRIVILEGES} ON TABLE {qualified_table} FROM {quote(role)}")


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0031_ticket_capacity"),
    ]

    operations = [
        migrations.RunPython(grant_attendant_runtime_access, revoke_attendant_runtime_access),
    ]
