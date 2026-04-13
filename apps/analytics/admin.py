"""Django Admin configuration for analytics."""

from django.contrib import admin

from apps.analytics.models import AgentPerformance, DailyReport, Metric


@admin.register(Metric)
class MetricAdmin(admin.ModelAdmin):
    list_display = ("metric_type", "date", "value")
    list_filter = ("metric_type",)
    readonly_fields = ("created_at",)


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "total_tickets_opened",
        "total_tickets_resolved",
        "sla_compliance_rate",
        "ai_deflection_rate",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(AgentPerformance)
class AgentPerformanceAdmin(admin.ModelAdmin):
    list_display = ("agent", "date", "tickets_handled", "tickets_resolved", "sla_breached_count")
    list_filter = ("date",)
    raw_id_fields = ("agent",)
