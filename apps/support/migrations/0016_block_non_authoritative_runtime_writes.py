"""Reject routing-state writes from non-authoritative JUDAH environments."""

from django.db import migrations


def create_runtime_guards(apps, schema_editor) -> None:
    """Install PostgreSQL triggers keyed by the JUDAH application_name."""
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
        BEGIN
            IF runtime_name ~ '(^|:)judah:(staging|development|test|preview)(:|$)' THEN
                RAISE EXCEPTION
                    'non-authoritative JUDAH runtime cannot mutate routing state: %%',
                    runtime_name
                    USING ERRCODE = '42501';
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
        BEFORE UPDATE OF
            status_enum,
            current_simultaneous_chats,
            hubspot_user_id,
            remote_availability_status,
            remote_out_of_office_hours,
            remote_working_hours,
            remote_timezone,
            availability_observed_at,
            availability_online_since,
            availability_sample_count,
            eligibility_state,
            eligibility_reason,
            eligibility_evaluated_at,
            availability_writer_id,
            availability_revision,
            availability_fencing_token
        ON agents
        FOR EACH ROW
        EXECUTE FUNCTION judah_reject_non_authoritative_runtime();
        """
    )
    for table in (
        "new_conversations",
        "assigned_conversations",
        "assignment_logs",
        "agent_availability_decisions",
        "availability_reconciliation_leases",
    ):
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
    for table in (
        "new_conversations",
        "assigned_conversations",
        "assignment_logs",
        "agent_availability_decisions",
        "availability_reconciliation_leases",
    ):
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
