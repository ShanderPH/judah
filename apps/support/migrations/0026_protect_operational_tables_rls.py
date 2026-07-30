"""Remove client-role access to Judah operational tables."""

from __future__ import annotations

import warnings

from django.db import migrations

PROTECTED_TABLES = (
    "conversation_instances",
    "conversation_events",
    "conversation_state_transitions",
    "agent_runs",
    "tool_call_audit_logs",
    "availability_reconciliation_leases",
    "agent_availability_decisions",
    "assignment_attempts",
    "support_conversation_cycles",
    "token_blacklist_blacklistedtoken",
    "token_blacklist_outstandingtoken",
)
CLIENT_ROLES = ("anon", "authenticated")
SUPABASE_DEFAULT_TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)


def _existing_tables(schema_editor) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        return set(schema_editor.connection.introspection.table_names(cursor))


def _existing_client_roles(schema_editor) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        return {str(row[0]) for row in cursor.fetchall()}


def _manageable_tables(schema_editor, tables: set[str]) -> set[str]:
    """Return tables the current database role can alter as an owner."""
    if not tables:
        return set()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_roles active_role ON active_role.rolname = current_user
            WHERE n.nspname = 'public'
              AND c.relname = ANY(%s)
              AND (
                  active_role.rolsuper
                  OR c.relowner = active_role.oid
                  OR pg_has_role(current_user, c.relowner, 'USAGE')
              )
            """,
            [list(tables)],
        )
        return {str(row[0]) for row in cursor.fetchall()}


def _warn_unmanageable_tables(tables: set[str], manageable: set[str]) -> None:
    skipped = sorted(tables - manageable)
    if skipped:
        warnings.warn(
            "Operational RLS requires a table-owner connection; skipped: "
            + ", ".join(skipped)
            + ". Apply the approved Supabase privileged migration separately.",
            RuntimeWarning,
            stacklevel=2,
        )


def protect_operational_tables(apps, schema_editor) -> None:
    """Revoke Data API roles and enable RLS as defense in depth."""
    del apps
    if schema_editor.connection.vendor != "postgresql":
        return
    existing = _existing_tables(schema_editor)
    protected = existing.intersection(PROTECTED_TABLES)
    manageable = _manageable_tables(schema_editor, protected)
    _warn_unmanageable_tables(protected, manageable)
    roles = _existing_client_roles(schema_editor)
    quote = schema_editor.connection.ops.quote_name
    with schema_editor.connection.cursor() as cursor:
        for table in PROTECTED_TABLES:
            if table not in manageable:
                continue
            qualified_table = f"public.{quote(table)}"
            cursor.execute(
                f"COMMENT ON TABLE {qualified_table} IS "
                f"'JUDAH operational data; direct anon/authenticated access is prohibited.'"
            )
            for role in CLIENT_ROLES:
                if role not in roles:
                    continue
                cursor.execute(f"REVOKE ALL PRIVILEGES ON TABLE {qualified_table} FROM {quote(role)}")
            cursor.execute(f"ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY")


def restore_supabase_client_grants(apps, schema_editor) -> None:
    """Restore the explicit pre-hotfix Supabase client-role grant snapshot."""
    del apps
    if schema_editor.connection.vendor != "postgresql":
        return
    existing = _existing_tables(schema_editor)
    protected = existing.intersection(PROTECTED_TABLES)
    manageable = _manageable_tables(schema_editor, protected)
    _warn_unmanageable_tables(protected, manageable)
    roles = _existing_client_roles(schema_editor)
    quote = schema_editor.connection.ops.quote_name
    privileges = ", ".join(SUPABASE_DEFAULT_TABLE_PRIVILEGES)
    with schema_editor.connection.cursor() as cursor:
        for table in PROTECTED_TABLES:
            if table not in manageable:
                continue
            qualified_table = f"public.{quote(table)}"
            cursor.execute(f"ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY")
            for role in CLIENT_ROLES:
                if role not in roles:
                    continue
                cursor.execute(f"GRANT {privileges} ON TABLE {qualified_table} TO {quote(role)}")


class Migration(migrations.Migration):
    """Apply least privilege without changing runtime ownership or BYPASSRLS."""

    dependencies = [
        ("ai_agents", "0006_remove_unique_conversation_instance_ticket"),
        ("support", "0025_administrative_action_audit"),
    ]

    operations = [
        migrations.RunPython(
            protect_operational_tables,
            restore_supabase_client_grants,
        ),
    ]
