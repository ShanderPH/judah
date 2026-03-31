"""
Fake initial migration for webhooks app.
Table webhook_events already exists in HelpdeskDB.
Table webhook_dead_letters is NEW and will be created.
Run with: python manage.py migrate webhooks --fake-initial
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="WebhookEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.TextField(db_index=True)),
                ("event_id", models.TextField(db_index=True)),
                ("object_id", models.TextField(db_index=True)),
                ("property_name", models.TextField(blank=True, null=True)),
                ("property_value", models.TextField(blank=True, null=True)),
                ("message_id", models.TextField(blank=True, null=True)),
                ("message_type", models.TextField(blank=True, null=True)),
                ("payload", models.JSONField()),
                ("received_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("processed", models.BooleanField(default=False)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("retry_count", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "webhook_events", "ordering": ["-received_at"]},
        ),
        migrations.CreateModel(
            name="DeadLetterQueue",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="dead_letter", to="webhooks.webhookevent")),
                ("failure_reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "webhook_dead_letters", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="webhookevent",
            index=models.Index(fields=["event_type", "processed"], name="webhook_events_type_processed_idx"),
        ),
    ]
