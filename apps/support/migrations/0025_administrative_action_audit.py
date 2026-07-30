import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0024_repair_queue_status_constraint"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdministrativeActionAudit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("actor_id", models.CharField(max_length=64)),
                ("actor_role", models.CharField(max_length=32)),
                ("action", models.CharField(max_length=96)),
                ("target_type", models.CharField(max_length=64)),
                ("target_id", models.CharField(blank=True, max_length=255)),
                ("reason", models.CharField(max_length=255)),
                ("correlation_id", models.CharField(db_index=True, max_length=64)),
                ("idempotency_key", models.CharField(blank=True, max_length=128, null=True)),
                ("request_fingerprint", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[("started", "Started"), ("succeeded", "Succeeded"), ("failed", "Failed")],
                        default="started",
                        max_length=16,
                    ),
                ),
                ("http_status", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("response_payload", models.JSONField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "support_administrative_action_audits",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["action", "created_at"], name="sup_adm_action_created_idx"),
                    models.Index(fields=["actor_id", "created_at"], name="sup_adm_actor_created_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(idempotency_key__isnull=False),
                        fields=("action", "idempotency_key"),
                        name="support_admin_audit_action_idempotency_uniq",
                    ),
                ],
            },
        ),
    ]
