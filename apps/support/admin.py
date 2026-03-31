"""Django Admin configuration for support."""

from django.contrib import admin

from apps.support.models import Agent, Metric, Queue, SLA, Ticket


@admin.register(Queue)
class QueueAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    search_fields = ("name",)


@admin.register(SLA)
class SLAAdmin(admin.ModelAdmin):
    list_display = ("name", "first_response_hours", "resolution_hours", "is_active")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "status", "priority", "channel", "queue", "assigned_to", "created_at")
    list_filter = ("status", "priority", "channel", "queue", "sla_breached")
    search_fields = ("subject", "customer_email", "hubspot_ticket_id", "church_external_id")
    raw_id_fields = ("queue", "sla", "assigned_to")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("user", "max_concurrent_tickets", "is_available")
    filter_horizontal = ("queues",)


@admin.register(Metric)
class MetricAdmin(admin.ModelAdmin):
    list_display = ("date", "queue", "total_tickets", "resolved_tickets", "sla_breached_count")
    list_filter = ("queue",)
    readonly_fields = ("created_at",)
