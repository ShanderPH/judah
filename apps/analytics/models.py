"""Models for analytics domain."""

from django.db import models


class Metric(models.Model):
    """Time-series metric data point."""

    class MetricType(models.TextChoices):
        TICKET_VOLUME = "ticket_volume", "Ticket Volume"
        RESOLUTION_TIME = "resolution_time", "Avg Resolution Time"
        FIRST_RESPONSE = "first_response", "Avg First Response"
        SLA_BREACH_RATE = "sla_breach_rate", "SLA Breach Rate"
        AGENT_SATISFACTION = "agent_satisfaction", "Agent Satisfaction"
        AI_DEFLECTION_RATE = "ai_deflection_rate", "AI Deflection Rate"

    metric_type = models.CharField(max_length=50, choices=MetricType.choices, db_index=True)
    date = models.DateField(db_index=True)
    value = models.FloatField()
    dimensions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_metrics"
        ordering = ["-date"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["metric_type", "date"]),
        ]

    def __str__(self) -> str:
        return f"{self.metric_type} @ {self.date}: {self.value}"


class DailyReport(models.Model):
    """Daily aggregated support report."""

    date = models.DateField(unique=True, db_index=True)
    total_tickets_opened = models.PositiveIntegerField(default=0)
    total_tickets_resolved = models.PositiveIntegerField(default=0)
    total_tickets_escalated = models.PositiveIntegerField(default=0)
    avg_resolution_hours = models.FloatField(default=0.0)
    avg_first_response_hours = models.FloatField(default=0.0)
    sla_compliance_rate = models.FloatField(default=0.0)
    ai_handled_count = models.PositiveIntegerField(default=0)
    ai_deflection_rate = models.FloatField(default=0.0)
    top_queues = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analytics_daily_reports"
        ordering = ["-date"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"Daily Report — {self.date}"


class AgentPerformance(models.Model):
    """Per-agent performance metrics for a given date."""

    from django.conf import settings

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="performance_records",
    )
    date = models.DateField(db_index=True)
    tickets_handled = models.PositiveIntegerField(default=0)
    tickets_resolved = models.PositiveIntegerField(default=0)
    avg_resolution_hours = models.FloatField(default=0.0)
    avg_first_response_hours = models.FloatField(default=0.0)
    sla_breached_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_agent_performance"
        unique_together = [("agent", "date")]  # noqa: RUF012
        ordering = ["-date"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.agent} — {self.date}"
