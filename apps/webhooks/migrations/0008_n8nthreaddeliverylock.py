from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


def protect_thread_lock_table(_apps, schema_editor) -> None:
    """Keep delivery leases inaccessible to Supabase client roles."""
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.connection.ops.quote_name
    qualified = f"public.{quote('n8n_thread_delivery_locks')}"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        roles = {str(row[0]) for row in cursor.fetchall()}
        cursor.execute(
            f"COMMENT ON TABLE {qualified} IS "
            "'JUDAH per-thread n8n delivery leases; direct client access is prohibited.'"
        )
        for role in roles:
            cursor.execute(f"REVOKE ALL PRIVILEGES ON TABLE {qualified} FROM {quote(role)}")
        cursor.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
        cursor.execute(
            "COMMENT ON INDEX public.idx_n8n_thread_lock_stale IS "
            "'Supports recovery of abandoned per-thread delivery leases.'"
        )


def restore_thread_lock_table_access(_apps, schema_editor) -> None:
    """Reverse only the access changes introduced by this migration."""
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.connection.ops.quote_name
    qualified = f"public.{quote('n8n_thread_delivery_locks')}"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        roles = {str(row[0]) for row in cursor.fetchall()}
        cursor.execute(f"ALTER TABLE {qualified} DISABLE ROW LEVEL SECURITY")
        for role in roles:
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                f"ON TABLE {qualified} TO {quote(role)}"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0007_webhookevent_delivery_method_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="N8nThreadDeliveryLock",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("hubspot_thread_id", models.CharField(max_length=100, unique=True)),
                ("locked_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "current_outbox",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="thread_delivery_leases",
                        to="webhooks.outboxevent",
                    ),
                ),
            ],
            options={"db_table": "n8n_thread_delivery_locks"},
        ),
        migrations.AddIndex(
            model_name="n8nthreaddeliverylock",
            index=models.Index(fields=["locked_at"], name="idx_n8n_thread_lock_stale"),
        ),
        migrations.RunPython(protect_thread_lock_table, restore_thread_lock_table_access),
    ]
