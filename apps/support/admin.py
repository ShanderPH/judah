"""Django Admin configuration for support."""

from django.contrib import admin

from apps.support.models import (
    Agent,
    AgentDailyTimeLog,
    AgentMetrics,
    AgentStatusHistory,
    Queue,
    Ticket,
    TicketJiraAssociation,
)


@admin.register(Queue)
class QueueAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    search_fields = ("name",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_id", "status", "priority", "ticket_church", "category", "created_at")
    list_filter = ("status", "priority", "category")
    search_fields = ("ticket_id", "customer_name", "ticket_church", "affected_module")
    readonly_fields = ("inserted_at", "updated_at")


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "agent_email",
        "status_enum",
        "team",
        "current_simultaneous_chats",
        "total_assignments",
        "sat_last_heartbeat_at",
        "is_active",
    )
    list_filter = ("status_enum", "team", "is_active")
    search_fields = ("name", "agent_email", "team")
    readonly_fields = ("created_at", "updated_at", "sat_last_heartbeat_at", "sat_last_count_sync_at")


@admin.register(AgentStatusHistory)
class AgentStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("agent", "old_status", "new_status", "changed_at", "sync_source")
    list_filter = ("new_status", "sync_source")
    readonly_fields = ("changed_at",)


@admin.register(AgentMetrics)
class AgentMetricsAdmin(admin.ModelAdmin):
    list_display = ("agent_id", "period_start", "period_end", "average_daily_tickets", "csat", "last_time_updated")
    list_filter = ("period_start",)
    readonly_fields = ("created_at",)


@admin.register(TicketJiraAssociation)
class TicketJiraAssociationAdmin(admin.ModelAdmin):
    list_display = ("ticket", "jira_issue_id", "association_active", "linked_at")
    list_filter = ("association_active",)
    readonly_fields = ("linked_at",)


@admin.register(AgentDailyTimeLog)
class AgentDailyTimeLogAdmin(admin.ModelAdmin):
    list_display = ("agent", "log_date", "online_time_seconds", "away_time_seconds", "status_transitions")
    list_filter = ("log_date",)
    search_fields = ("agent__name",)
    readonly_fields = ("created_at", "updated_at")
