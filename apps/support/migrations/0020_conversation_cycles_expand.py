"""Expansive, reversible conversation-cycle schema (Gate B, DB-02).

Adds the ``support_conversation_cycles`` table and nullable ``cycle_id`` FKs
on the six operational tables. Existing rows, constraints, and behavior are
preserved: no backfill, no dropped uniques, no NOT NULL additions.

Index/constraint justification:
- ``uniq_conv_cycle_natural_key``: idempotency of one proven stage-entry
  occurrence; its backing index also serves natural-key lookups (leftmost
  columns), so no separate lookup index is created.
- ``uniq_active_conv_cycle_ticket``: partial unique index enforcing at most
  one active (queued/assigned/repair_required) cycle per account + ticket.
- ``idx_cycle_ticket_opened``: admission loads every cycle of a ticket in
  occurrence order (duplicate/stale detection).
- ``idx_cycle_state_opened``: readiness/repair scan active or broken cycles
  by age.

The runtime writer guard trigger from ``0016`` is extended to the new table
only. The reverse migration drops solely the objects added here (table, FKs,
indexes, constraints, and the new trigger); the guard function and the
pre-existing triggers are untouched.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models

CYCLE_GUARD_TRIGGER = "trg_guard_support_conversation_cycles_runtime"
CYCLE_TABLE = "support_conversation_cycles"


def create_cycle_guard(apps, schema_editor) -> None:
    """Extend the existing runtime writer guard to the cycle table."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        f"""
        DROP TRIGGER IF EXISTS {CYCLE_GUARD_TRIGGER} ON {CYCLE_TABLE};
        CREATE TRIGGER {CYCLE_GUARD_TRIGGER}
        BEFORE INSERT OR UPDATE OR DELETE ON {CYCLE_TABLE}
        FOR EACH ROW
        EXECUTE FUNCTION judah_reject_non_authoritative_runtime();
        """
    )


def drop_cycle_guard(apps, schema_editor) -> None:
    """Remove only the cycle-table guard trigger added by this migration."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {CYCLE_GUARD_TRIGGER} ON {CYCLE_TABLE};")


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0019_fix_agent_assignment_timestamp_timezone"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportConversationCycle",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("cycle_key", models.TextField(unique=True)),
                ("source_system", models.TextField(default="hubspot")),
                ("source_account_id", models.TextField()),
                ("hubspot_ticket_id", models.TextField(db_index=True)),
                ("entered_stage_at", models.DateTimeField()),
                ("source_event_id", models.TextField(blank=True, default="")),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("assigned", "Assigned"),
                            ("repair_required", "Repair Required"),
                            ("closed", "Closed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="queued",
                        max_length=20,
                    ),
                ),
                ("opened_at", models.DateTimeField()),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "support_conversation_cycles",
                "ordering": ["-entered_stage_at"],
                "indexes": [
                    models.Index(fields=["hubspot_ticket_id", "entered_stage_at"], name="idx_cycle_ticket_opened"),
                    models.Index(fields=["state", "entered_stage_at"], name="idx_cycle_state_opened"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_system", "source_account_id", "hubspot_ticket_id", "entered_stage_at"),
                        name="uniq_conv_cycle_natural_key",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("state__in", ["queued", "assigned", "repair_required"])),
                        fields=("source_account_id", "hubspot_ticket_id"),
                        name="uniq_active_conv_cycle_ticket",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="assignedconversation",
            name="cycle",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assigned_conversations",
                to="support.supportconversationcycle",
            ),
        ),
        migrations.AddField(
            model_name="assignmentattempt",
            name="cycle",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignment_attempts",
                to="support.supportconversationcycle",
            ),
        ),
        migrations.AddField(
            model_name="assignmentlog",
            name="cycle",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignment_logs",
                to="support.supportconversationcycle",
            ),
        ),
        migrations.AddField(
            model_name="closedconversation",
            name="cycle",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="closed_conversations",
                to="support.supportconversationcycle",
            ),
        ),
        migrations.AddField(
            model_name="conversationreassignment",
            name="cycle",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reassignments",
                to="support.supportconversationcycle",
            ),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="cycle",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="new_conversations",
                to="support.supportconversationcycle",
            ),
        ),
        migrations.RunPython(create_cycle_guard, drop_cycle_guard),
    ]
