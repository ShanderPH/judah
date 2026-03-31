"""Django Admin configuration for webhooks."""

from django.contrib import admin

from apps.webhooks.models import DeadLetterQueue, WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "object_id", "processed", "retry_count", "received_at")
    list_filter = ("event_type", "processed")
    search_fields = ("event_type", "event_id", "object_id")
    readonly_fields = ("payload", "received_at", "created_at", "processed_at")


@admin.register(DeadLetterQueue)
class DeadLetterQueueAdmin(admin.ModelAdmin):
    list_display = ("event", "created_at")
    readonly_fields = ("event", "failure_reason", "created_at")
