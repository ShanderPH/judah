"""Allow routing-state writes only from explicitly trusted database roles."""

from django.db import migrations

TRUSTED_WRITER_ROLES = (
    "judah_production_runtime",
    "judah_schema_migration",
    "judah_break_glass",
)

GUARDED_TABLES = (
    "new_conversations",
    "assigned_conversations",
    "assignment_logs",
    "agent_status_history",
    "agent_availability_decisions",
    "availability_reconciliation_leases",
    "conversation_reassignments",
)


def create_runtime_guards(apps, schema_editor) -> None:
    """Install PostgreSQL triggers keyed by database identity."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION judah_reject_non_authoritative_runtime()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            runtime_name text := lower(current_setting('application_name', true));
            writer_role text := lower(current_user);
            is_local_test_migration boolean :=
                current_database() ~ '^(test_)?judah_test($|_)'
                AND lower(current_user) = 'postgres'
                AND lower(session_user) = 'postgres'
                AND runtime_name = 'judah:local-test:pytest';
        BEGIN
            IF NOT (
                writer_role IN (
                    'judah_production_runtime',
                    'judah_schema_migration',
                    'judah_break_glass'
                )
                OR is_local_test_migration
            ) THEN
                RAISE EXCEPTION
                    'untrusted JUDAH database role cannot mutate routing state: role=%% application_name=%%',
                    writer_role,
                    runtime_name
                    USING ERRCODE = '42501';
            END IF;
            IF NOT is_local_test_migration
                AND coalesce(runtime_name, '') !~ '^judah:[a-z0-9_-]+:[a-z0-9_-]+'
            THEN
                RAISE EXCEPTION
                    'trusted JUDAH writer requires diagnostic application_name: role=%%',
                    writer_role
                    USING ERRCODE = '42501';
            END IF;
            IF writer_role = 'judah_break_glass' THEN
                RAISE LOG
                    'JUDAH break-glass routing write: table=%% operation=%% application_name=%%',
                    TG_TABLE_NAME,
                    TG_OP,
                    runtime_name;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    schema_editor.execute(
        """
        DROP TRIGGER IF EXISTS trg_guard_agent_routing_state ON agents;
        CREATE TRIGGER trg_guard_agent_routing_state
        BEFORE INSERT OR UPDATE OR DELETE
        ON agents
        FOR EACH ROW
        EXECUTE FUNCTION judah_reject_non_authoritative_runtime();
        """
    )
    for table in GUARDED_TABLES:
        trigger = f"trg_guard_{table}_runtime"
        schema_editor.execute(
            f"""
            DROP TRIGGER IF EXISTS {trigger} ON {table};
            CREATE TRIGGER {trigger}
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION judah_reject_non_authoritative_runtime();
            """
        )


def drop_runtime_guards(apps, schema_editor) -> None:
    """Remove the PostgreSQL runtime write guards."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS trg_guard_agent_routing_state ON agents;")
    for table in GUARDED_TABLES:
        trigger = f"trg_guard_{table}_runtime"
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table};")
    schema_editor.execute("DROP FUNCTION IF EXISTS judah_reject_non_authoritative_runtime();")


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0015_absence_safe_eligibility"),
    ]

    operations = [
        migrations.RunPython(create_runtime_guards, drop_runtime_guards),
    ]
