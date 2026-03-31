"""
Fake initial migration for support app.
Tables agents, tickets, agent_metrics, agent_status_history,
ticket_jira_associations already exist in HelpdeskDB.
Run with: python manage.py migrate support --fake-initial
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Queue",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=200, unique=True)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "queue_settings", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Agent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.TextField()),
                ("agent_email", models.TextField(unique=True)),
                ("hubspot_owner_id", models.BigIntegerField()),
                ("internal_user_id", models.BigIntegerField(blank=True, null=True)),
                ("team", models.TextField(blank=True, null=True)),
                ("manager_email", models.TextField(blank=True, null=True)),
                ("status_enum", models.CharField(choices=[("online", "Online"), ("away", "Away"), ("offline", "Offline"), ("busy", "Busy")], default="away", max_length=20)),
                ("current_simultaneous_chats", models.BigIntegerField(default=0)),
                ("max_simultaneous_chats", models.IntegerField(default=5)),
                ("auto_assign_enabled", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(blank=True, null=True)),
                ("working_hours", models.JSONField(blank=True, null=True)),
                ("skills", models.JSONField(blank=True, null=True)),
                ("timezone", models.TextField(default="America/Sao_Paulo")),
                ("last_assignment_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
            ],
            options={"db_table": "agents", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("ticket_id", models.TextField(db_index=True, unique=True)),
                ("customer_name", models.TextField(blank=True, null=True)),
                ("ticket_church", models.TextField(blank=True, db_index=True, null=True)),
                ("category", models.TextField(blank=True, null=True)),
                ("priority", models.TextField(blank=True, db_index=True, null=True)),
                ("status", models.TextField(blank=True, db_index=True, null=True)),
                ("affected_device", models.TextField(blank=True, null=True)),
                ("scope_of_impact", models.TextField(blank=True, null=True)),
                ("affected_module", models.TextField(blank=True, null=True)),
                ("affected_functionality", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(db_index=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("inserted_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "tickets", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AgentStatusHistory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("agent", models.ForeignKey(db_column="agent_id", on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="support.agent")),
                ("old_status", models.CharField(blank=True, max_length=20, null=True)),
                ("new_status", models.CharField(max_length=20)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("sync_source", models.TextField(default="internal")),
                ("metadata", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
            ],
            options={"db_table": "agent_status_history", "ordering": ["-changed_at"]},
        ),
        migrations.CreateModel(
            name="AgentMetrics",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("agent_id", models.BigIntegerField(db_index=True)),
                ("period_start", models.DateField(blank=True, null=True)),
                ("period_end", models.DateField(blank=True, null=True)),
                ("average_online_time", models.FloatField(default=0.0)),
                ("average_away_time", models.FloatField(default=0.0)),
                ("average_daily_tickets", models.BigIntegerField(default=0)),
                ("average_response_time_min", models.FloatField(default=0.0)),
                ("average_ticket_time_min", models.FloatField(default=0.0)),
                ("tickets_transfer", models.BigIntegerField(default=0)),
                ("csat", models.BigIntegerField(default=0)),
                ("total_chats", models.IntegerField(default=0)),
                ("chats_closed", models.IntegerField(default=0)),
                ("first_response_time_avg_min", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("resolution_rate", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("customer_satisfaction_avg", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("last_time_updated", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
            ],
            options={"db_table": "agent_metrics", "ordering": ["-last_time_updated"]},
        ),
        migrations.CreateModel(
            name="TicketJiraAssociation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("ticket", models.ForeignKey(db_column="ticket_id", on_delete=django.db.models.deletion.CASCADE, related_name="jira_associations", to="support.ticket")),
                ("jira_issue_id", models.UUIDField(db_index=True)),
                ("linked_at", models.DateTimeField(auto_now_add=True)),
                ("association_active", models.BooleanField(default=True)),
            ],
            options={"db_table": "ticket_jira_associations"},
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["status", "priority"], name="tickets_status_priority_idx"),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["ticket_church", "status"], name="tickets_church_status_idx"),
        ),
    ]
