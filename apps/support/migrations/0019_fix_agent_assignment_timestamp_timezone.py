"""Align the legacy agent assignment clock with Django timezone handling."""

from collections import defaultdict

from django.db import migrations

_VIEW_NAME = "v_agent_performance_realtime"
_VIEW_DEFINITION = """
SELECT
    a.id,
    a.name,
    a.agent_email,
    a.status_enum AS current_status,
    a.current_simultaneous_chats,
    a.max_simultaneous_chats,
    round(
        a.current_simultaneous_chats::numeric
        / NULLIF(a.max_simultaneous_chats, 0)::numeric
        * 100::numeric,
        2
    ) AS capacity_utilization,
    count(
        CASE
            WHEN (cs.status = ANY (ARRAY['assigned'::text, 'active'::text]))
              OR (cs.status_enum = ANY (
                    ARRAY[
                        'assigned'::public.chat_status_enum,
                        'active'::public.chat_status_enum
                    ]
                ))
            THEN 1
            ELSE NULL::integer
        END
    ) AS active_chats,
    count(
        CASE
            WHEN cs.closed_at::date = CURRENT_DATE THEN 1
            ELSE NULL::integer
        END
    ) AS chats_closed_today,
    avg(
        CASE
            WHEN cs.closed_at::date = CURRENT_DATE THEN cs.response_time_seconds
            ELSE NULL::numeric
        END
    ) AS avg_response_time_today,
    a.last_assignment_at,
    a.updated_at AS last_status_update
FROM public.agents AS a
LEFT JOIN public.chat_sessions AS cs
    ON cs.agent_id = a.hubspot_owner_id
WHERE a.is_active = true
GROUP BY
    a.id,
    a.name,
    a.agent_email,
    a.status_enum,
    a.current_simultaneous_chats,
    a.max_simultaneous_chats,
    a.last_assignment_at,
    a.updated_at
ORDER BY a.name
"""
_VALID_PRIVILEGES = {
    "DELETE",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "TRIGGER",
    "TRUNCATE",
    "UPDATE",
}


def _column_type(schema_editor) -> str | None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'agents'
              AND column_name = 'last_assignment_at'
            """
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


def _view_metadata(schema_editor) -> tuple[str, str | None, dict[str, list[str]]] | None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_userbyid(c.relowner), obj_description(c.oid, 'pg_class')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s
            """,
            [_VIEW_NAME],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        cursor.execute(
            """
            SELECT grantee, privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY grantee, privilege_type
            """,
            [_VIEW_NAME],
        )
        grants: defaultdict[str, list[str]] = defaultdict(list)
        for grantee, privilege in cursor.fetchall():
            privilege_name = str(privilege).upper()
            if privilege_name in _VALID_PRIVILEGES:
                grants[str(grantee)].append(privilege_name)
    return str(row[0]), str(row[1]) if row[1] is not None else None, dict(grants)


def _restore_view(schema_editor, metadata: tuple[str, str | None, dict[str, list[str]]]) -> None:
    owner, comment, grants = metadata
    schema_editor.execute(f"CREATE VIEW public.{_VIEW_NAME} WITH (security_invoker = true) AS {_VIEW_DEFINITION}")
    schema_editor.execute(f"ALTER VIEW public.{_VIEW_NAME} OWNER TO {schema_editor.quote_name(owner)}")
    if comment is not None:
        schema_editor.execute(
            f"COMMENT ON VIEW public.{_VIEW_NAME} IS %s",
            params=[comment],
        )
    for grantee, privileges in grants.items():
        schema_editor.execute(
            f"GRANT {', '.join(privileges)} ON TABLE public.{_VIEW_NAME} TO {schema_editor.quote_name(grantee)}"
        )


def _alter_assignment_clock(schema_editor, *, source_type: str, target_type: str) -> None:
    if _column_type(schema_editor) != source_type:
        return
    metadata = _view_metadata(schema_editor)
    if metadata is not None:
        schema_editor.execute(f"DROP VIEW public.{_VIEW_NAME}")
    schema_editor.execute(
        "ALTER TABLE public.agents "
        f"ALTER COLUMN last_assignment_at TYPE {target_type} "
        "USING last_assignment_at AT TIME ZONE 'UTC'"
    )
    if metadata is not None:
        _restore_view(schema_editor, metadata)


def use_timezone_aware_assignment_clock(apps, schema_editor) -> None:
    """Convert the legacy naive timestamp to UTC-aware PostgreSQL storage."""
    if schema_editor.connection.vendor != "postgresql":
        return
    _alter_assignment_clock(
        schema_editor,
        source_type="timestamp without time zone",
        target_type="timestamp with time zone",
    )


def restore_naive_assignment_clock(apps, schema_editor) -> None:
    """Restore the legacy UTC-naive representation for rollback."""
    if schema_editor.connection.vendor != "postgresql":
        return
    _alter_assignment_clock(
        schema_editor,
        source_type="timestamp with time zone",
        target_type="timestamp without time zone",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0018_new_ticket_assignment_rollout_gate"),
    ]

    operations = [
        migrations.RunPython(
            use_timezone_aware_assignment_clock,
            restore_naive_assignment_clock,
        ),
    ]
