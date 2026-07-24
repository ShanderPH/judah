"""Models for webhooks domain — mapped to existing webhook_events table."""

import uuid

from django.db import models


class WebhookEvent(models.Model):
    """Incoming webhook event — maps to existing webhook_events table in HelpdeskDB."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deduplication_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    event_type = models.TextField(db_index=True)
    event_id = models.TextField(db_index=True)
    object_id = models.TextField(db_index=True)
    property_name = models.TextField(null=True, blank=True)
    property_value = models.TextField(null=True, blank=True)
    message_id = models.TextField(null=True, blank=True)
    message_type = models.TextField(null=True, blank=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "webhook_events"
        ordering = ["-received_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["event_type", "processed"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} / {self.object_id} [processed={self.processed}]"


class DeadLetterQueue(models.Model):
    """Permanently failed webhook events for manual review — new JUDAH table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.OneToOneField(WebhookEvent, on_delete=models.CASCADE, related_name="dead_letter")
    failure_reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "webhook_dead_letters"
        ordering = ["-created_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"DLQ: {self.event}"
