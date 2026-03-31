"""
Migration: Add auto-assignment queue tables.

Tables new_conversations, assigned_conversations, queue_performance_metrics
were already created in Supabase via MCP migration.
AssignmentLog maps to the existing assignment_logs table (extended with
queue_wait_seconds, entered_queue_at, pipeline_id columns).

Run with: python manage.py migrate support
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0001_initial"),
    ]

    operations = [
        # ----------------------------------------------------------------
        # AssignmentLog — maps to existing assignment_logs table (extended)
        # ----------------------------------------------------------------
        migrations.CreateModel(
            name="AssignmentLog",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("ticket_id", models.TextField(db_index=True)),
                (
                    "agent",
                    models.ForeignKey(
                        blank=True,
                        db_column="agent_id",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assignment_logs",
                        to="support.agent",
                    ),
                ),
                ("agent_name", models.TextField()),
                ("hubspot_owner_id", models.BigIntegerField(blank=True, null=True)),
                ("assignment_type", models.TextField(default="auto")),
                ("assigned_by", models.TextField(blank=True, null=True)),
                ("pipeline_id", models.TextField(blank=True, null=True)),
                ("entered_queue_at", models.DateTimeField(blank=True, null=True)),
                (
                    "queue_wait_seconds",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "assignment_logs",
                "ordering": ["-assigned_at"],
            },
        ),
        # ----------------------------------------------------------------
        # NewConversation — maps to new_conversations table
        # ----------------------------------------------------------------
        migrations.CreateModel(
            name="NewConversation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("hubspot_ticket_id", models.TextField(db_index=True, unique=True)),
                ("pipeline_id", models.TextField(default="636459134")),
                ("contact_name", models.TextField(blank=True, null=True)),
                ("contact_email", models.TextField(blank=True, null=True)),
                ("priority", models.TextField(blank=True, null=True)),
                ("subject", models.TextField(blank=True, null=True)),
                ("entered_queue_at", models.DateTimeField(db_index=True)),
                ("is_pending", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "new_conversations",
                "ordering": ["entered_queue_at"],
            },
        ),
        migrations.AddIndex(
            model_name="newconversation",
            index=models.Index(fields=["is_pending", "entered_queue_at"], name="idx_nc_pending_queue"),
        ),
        # ----------------------------------------------------------------
        # AssignedConversation — maps to assigned_conversations table
        # ----------------------------------------------------------------
        migrations.CreateModel(
            name="AssignedConversation",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("hubspot_ticket_id", models.TextField(db_index=True, unique=True)),
                (
                    "agent",
                    models.ForeignKey(
                        blank=True,
                        db_column="agent_id",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_conversations",
                        to="support.agent",
                    ),
                ),
                ("hubspot_owner_id", models.BigIntegerField(db_index=True)),
                ("agent_name", models.TextField()),
                ("pipeline_id", models.TextField(default="636459134")),
                ("entered_queue_at", models.DateTimeField(blank=True, null=True)),
                ("assigned_at", models.DateTimeField(db_index=True)),
                (
                    "queue_wait_seconds",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                ("closed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("closed_by_owner_id", models.BigIntegerField(blank=True, null=True)),
                ("closed_by_agent_name", models.TextField(blank=True, null=True)),
                (
                    "total_handle_time_minutes",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                ("contact_name", models.TextField(blank=True, null=True)),
                ("contact_email", models.TextField(blank=True, null=True)),
                ("priority", models.TextField(blank=True, null=True)),
                ("subject", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "assigned_conversations",
                "ordering": ["-assigned_at"],
            },
        ),
        migrations.AddIndex(
            model_name="assignedconversation",
            index=models.Index(fields=["hubspot_owner_id", "assigned_at"], name="idx_ac_owner_date"),
        ),
        migrations.AddIndex(
            model_name="assignedconversation",
            index=models.Index(fields=["assigned_at"], name="idx_ac_assigned_at"),
        ),
        # ----------------------------------------------------------------
        # QueuePerformanceMetrics — maps to queue_performance_metrics table
        # ----------------------------------------------------------------
        migrations.CreateModel(
            name="QueuePerformanceMetrics",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("metric_date", models.DateField(db_index=True, unique=True)),
                ("total_entered_queue", models.IntegerField(default=0)),
                ("total_assigned", models.IntegerField(default=0)),
                ("total_closed", models.IntegerField(default=0)),
                (
                    "avg_queue_wait_seconds",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                (
                    "min_queue_wait_seconds",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                (
                    "max_queue_wait_seconds",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                (
                    "p50_queue_wait_seconds",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                (
                    "p95_queue_wait_seconds",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                (
                    "avg_handle_time_minutes",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
                ),
                ("assignments_by_agent", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "queue_performance_metrics",
                "ordering": ["-metric_date"],
            },
        ),
    ]
