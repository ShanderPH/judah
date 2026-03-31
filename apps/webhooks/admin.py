"""Django Admin configuration for webhooks."""

from django.contrib import admin

from apps.webhooks.models import DeadLetterQueue, WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("source", "event_type", "status", "retry_count", "created_at")
    list_filter = ("source", "status")
    search_fields = ("event_type",)
    readonly_fields = ("payload", "created_at", "processed_at")


@admin.register(DeadLetterQueue)
class DeadLetterQueueAdmin(admin.ModelAdmin):
    list_display = ("event", "created_at")
    readonly_fields = ("event", "failure_reason", "created_at")
