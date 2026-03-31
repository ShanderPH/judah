"""Django Admin configuration for ai_agents."""

from django.contrib import admin

from apps.ai_agents.models import AgentMemory, AgentSession, AgentTrace


@admin.register(AgentSession)
class AgentSessionAdmin(admin.ModelAdmin):
    list_display = ("session_id", "agent_type", "channel", "user_identifier", "is_active", "created_at")
    list_filter = ("agent_type", "channel", "is_active")
    search_fields = ("session_id", "user_identifier", "hubspot_contact_id", "church_external_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AgentMemory)
class AgentMemoryAdmin(admin.ModelAdmin):
    list_display = ("session", "key", "updated_at")
    search_fields = ("session__session_id", "key")


@admin.register(AgentTrace)
class AgentTraceAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "tool_name", "tokens_used", "latency_ms", "created_at")
    list_filter = ("role",)
    search_fields = ("session__session_id", "content", "tool_name")
    readonly_fields = ("created_at",)
