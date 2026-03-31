"""
Initial migration for analytics app.
Tables analytics_metrics, analytics_daily_reports, analytics_agent_performance
were created via create_judah_new_tables migration in Supabase.
Run with: python manage.py migrate analytics --fake-initial
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Metric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "metric_type",
                    models.CharField(
                        choices=[
                            ("ticket_volume", "Ticket Volume"),
                            ("resolution_time", "Avg Resolution Time"),
                            ("first_response", "Avg First Response"),
                            ("sla_breach_rate", "SLA Breach Rate"),
                            ("agent_satisfaction", "Agent Satisfaction"),
                            ("ai_deflection_rate", "AI Deflection Rate"),
                        ],
                        db_index=True,
                        max_length=50,
                    ),
                ),
                ("date", models.DateField(db_index=True)),
                ("value", models.FloatField()),
                ("dimensions", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "analytics_metrics", "ordering": ["-date"]},
        ),
        migrations.CreateModel(
            name="DailyReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("date", models.DateField(db_index=True, unique=True)),
                ("total_tickets_opened", models.PositiveIntegerField(default=0)),
                ("total_tickets_resolved", models.PositiveIntegerField(default=0)),
                ("total_tickets_escalated", models.PositiveIntegerField(default=0)),
                ("avg_resolution_hours", models.FloatField(default=0.0)),
                ("avg_first_response_hours", models.FloatField(default=0.0)),
                ("sla_compliance_rate", models.FloatField(default=0.0)),
                ("ai_handled_count", models.PositiveIntegerField(default=0)),
                ("ai_deflection_rate", models.FloatField(default=0.0)),
                ("top_queues", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "analytics_daily_reports", "ordering": ["-date"]},
        ),
        migrations.CreateModel(
            name="AgentPerformance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "agent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="performance_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("date", models.DateField(db_index=True)),
                ("tickets_handled", models.PositiveIntegerField(default=0)),
                ("tickets_resolved", models.PositiveIntegerField(default=0)),
                ("avg_resolution_hours", models.FloatField(default=0.0)),
                ("avg_first_response_hours", models.FloatField(default=0.0)),
                ("sla_breached_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "analytics_agent_performance", "ordering": ["-date"]},
        ),
        migrations.AlterUniqueTogether(
            name="agentperformance",
            unique_together={("agent", "date")},
        ),
        migrations.AddIndex(
            model_name="metric",
            index=models.Index(fields=["metric_type", "date"], name="analytics_metrics_type_date_idx"),
        ),
    ]
