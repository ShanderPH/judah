"""Persist durable assignment attempts and database-backed queue claims."""

import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def create_attempt_runtime_guard(apps, schema_editor) -> None:
    """Protect durable attempts with the authoritative writer trigger."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        DROP TRIGGER IF EXISTS trg_guard_assignment_attempts_runtime
            ON assignment_attempts;
        CREATE TRIGGER trg_guard_assignment_attempts_runtime
        BEFORE INSERT OR UPDATE OR DELETE ON assignment_attempts
        FOR EACH ROW
        EXECUTE FUNCTION judah_reject_non_authoritative_runtime();
        """
    )


def drop_attempt_runtime_guard(apps, schema_editor) -> None:
    """Remove the durable-attempt writer trigger."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS trg_guard_assignment_attempts_runtime ON assignment_attempts;")


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0016_block_non_authoritative_runtime_writes"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="agent",
            constraint=models.CheckConstraint(
                condition=Q(current_simultaneous_chats__gte=0),
                name="agent_current_chats_nonnegative",
            ),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="claim_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="claim_owner_token",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="newconversation",
            name="claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="AssignmentAttempt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("idempotency_key", models.UUIDField(editable=False, unique=True)),
                ("ticket_id", models.TextField(db_index=True)),
                ("eligibility_revision", models.PositiveBigIntegerField()),
                ("desired_hubspot_owner_id", models.BigIntegerField()),
                ("prior_observed_owner_id", models.BigIntegerField(blank=True, null=True)),
                ("decision_snapshot", models.JSONField(default=dict)),
                ("decision_reason", models.CharField(max_length=64)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("reserved", "Reserved"),
                            ("external_applied", "External Applied"),
                            ("completed", "Completed"),
                            ("compensating", "Compensating"),
                            ("compensated", "Compensated"),
                            ("retryable", "Retryable"),
                            ("repair_required", "Repair Required"),
                        ],
                        default="reserved",
                        max_length=24,
                    ),
                ),
                (
                    "assignment_type",
                    models.CharField(
                        choices=[
                            ("automatic", "Automatic"),
                            ("manual", "Manual"),
                            ("forced", "Forced"),
                        ],
                        default="automatic",
                        max_length=16,
                    ),
                ),
                ("requested_by", models.CharField(blank=True, default="", max_length=255)),
                ("override_reason", models.CharField(blank=True, default="", max_length=255)),
                (
                    "provider_request_classification",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "provider_result_classification",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("reserved_at", models.DateTimeField()),
                ("external_applied_at", models.DateTimeField(blank=True, null=True)),
                ("finalized_at", models.DateTimeField(blank=True, null=True)),
                ("compensation_started_at", models.DateTimeField(blank=True, null=True)),
                ("compensated_at", models.DateTimeField(blank=True, null=True)),
                ("retry_count", models.PositiveIntegerField(default=0)),
                ("next_retry_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "queue_row",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="durable_attempts",
                        to="support.newconversation",
                    ),
                ),
                (
                    "selected_agent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignment_attempts",
                        to="support.agent",
                    ),
                ),
            ],
            options={
                "db_table": "assignment_attempts",
                "indexes": [
                    models.Index(
                        fields=["state", "next_retry_at"],
                        name="idx_attempt_retry_scan",
                    ),
                    models.Index(
                        fields=["ticket_id", "state"],
                        name="idx_attempt_ticket_state",
                    ),
                    models.Index(fields=["reserved_at"], name="idx_attempt_stuck_scan"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=Q(
                            state__in=[
                                "reserved",
                                "external_applied",
                                "compensating",
                                "retryable",
                                "repair_required",
                            ]
                        ),
                        fields=("ticket_id",),
                        name="uniq_live_assignment_attempt_ticket",
                    ),
                    models.UniqueConstraint(
                        condition=Q(state="completed"),
                        fields=("ticket_id",),
                        name="uniq_completed_assignment_ticket",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="assignmentlog",
            name="assignment_attempt",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assignment_log",
                to="support.assignmentattempt",
            ),
        ),
        migrations.RunPython(create_attempt_runtime_guard, drop_attempt_runtime_guard),
    ]
