"""
Initial migration for ai_agents app.
Tables agent_sessions, agent_memories, agent_traces were created
via create_judah_new_tables migration in Supabase.
Run with: python manage.py migrate ai_agents --fake-initial
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AgentSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("session_id", models.CharField(db_index=True, max_length=100, unique=True)),
                ("agent_type", models.CharField(
                    choices=[("salomao", "Salomão"), ("heimdall", "Heimdall")],
                    default="salomao",
                    max_length=20,
                )),
                ("user_identifier", models.CharField(blank=True, db_index=True, max_length=255)),
                ("channel", models.CharField(blank=True, max_length=50)),
                ("hubspot_contact_id", models.CharField(blank=True, db_index=True, max_length=50)),
                ("church_external_id", models.CharField(blank=True, db_index=True, max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "agent_sessions", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AgentMemory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("session", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="memories",
                    to="ai_agents.agentsession",
                )),
                ("key", models.CharField(max_length=200)),
                ("value", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "agent_memories"},
        ),
        migrations.CreateModel(
            name="AgentTrace",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("session", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="traces",
                    to="ai_agents.agentsession",
                )),
                ("role", models.CharField(
                    choices=[("user", "User"), ("assistant", "Assistant"), ("tool", "Tool")],
                    max_length=20,
                )),
                ("content", models.TextField()),
                ("tool_name", models.CharField(blank=True, max_length=100)),
                ("tool_input", models.JSONField(blank=True, null=True)),
                ("tool_output", models.JSONField(blank=True, null=True)),
                ("tokens_used", models.PositiveIntegerField(default=0)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={"db_table": "agent_traces", "ordering": ["session", "created_at"]},
        ),
        migrations.AlterUniqueTogether(
            name="agentmemory",
            unique_together={("session", "key")},
        ),
    ]
