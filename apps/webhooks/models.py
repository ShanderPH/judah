"""Models for webhooks domain."""

from django.db import models


class WebhookEvent(models.Model):
    """Stores an incoming webhook event for audit and retry purposes."""

    class Source(models.TextChoices):
        HUBSPOT = "hubspot", "HubSpot"
        JIRA = "jira", "Jira"
        N8N = "n8n", "N8N"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"
        DEAD_LETTER = "dead_letter", "Dead Letter"

    source = models.CharField(max_length=20, choices=Source.choices, db_index=True)
    event_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "webhook_events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.source} / {self.event_type} [{self.status}]"


class DeadLetterQueue(models.Model):
    """Permanently failed webhook events for manual review."""

    event = models.OneToOneField(WebhookEvent, on_delete=models.CASCADE, related_name="dead_letter")
    failure_reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "webhook_dead_letters"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DLQ: {self.event}"
