"""Models for webhooks domain — mapped to existing webhook_events table."""

import uuid

from django.db import models


class WebhookEvent(models.Model):
    """Incoming webhook event — maps to existing webhook_events table in HelpdeskDB."""

    class DeliveryMethod(models.TextChoices):
        WEBHOOK = "webhook", "Webhook"
        RECONCILIATION = "reconciliation", "Reconciliation"

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        READY = "READY", "Ready"
        IGNORED = "IGNORED", "Ignored"
        ERROR = "ERROR", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=50, default="", db_index=True)
    deduplication_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    event_type = models.TextField(db_index=True)
    event_id = models.TextField(db_index=True)
    object_id = models.TextField(db_index=True)
    property_name = models.TextField(null=True, blank=True)
    property_value = models.TextField(null=True, blank=True)
    portal_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    hubspot_thread_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    hubspot_ticket_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    hubspot_contact_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    message_id = models.TextField(null=True, blank=True, db_index=True)
    message_type = models.TextField(null=True, blank=True)
    delivery_method = models.CharField(max_length=20, choices=DeliveryMethod.choices, blank=True, default="")
    occurred_at = models.DateTimeField(null=True, blank=True, db_index=True)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
        db_index=True,
    )
    ignored_reason = models.CharField(max_length=100, blank=True, default="")
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


class OutboxEvent(models.Model):
    """Immutable n8n delivery body plus mutable delivery bookkeeping."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        RETRY_SCHEDULED = "RETRY_SCHEDULED", "Retry scheduled"
        DELIVERED = "DELIVERED", "Delivered"
        DEAD_LETTER = "DEAD_LETTER", "Dead letter"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    webhook_event = models.OneToOneField(WebhookEvent, on_delete=models.PROTECT, related_name="outbox_event")
    destination = models.CharField(max_length=50, default="n8n_bot")
    event_type = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=255, unique=True)
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=8)
    available_at = models.DateTimeField(db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    last_http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "n8n_outbox_events"
        ordering = ["available_at", "created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["status", "available_at"], name="idx_n8n_outbox_poll"),
            models.Index(fields=["status", "locked_at"], name="idx_n8n_outbox_stuck"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} / {self.idempotency_key} [{self.status}]"


class N8nThreadDeliveryLock(models.Model):
    """Durable lease that serializes n8n deliveries for one HubSpot thread."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_thread_id = models.CharField(max_length=100, unique=True)
    current_outbox = models.ForeignKey(
        OutboxEvent,
        on_delete=models.PROTECT,
        related_name="thread_delivery_leases",
        null=True,
        blank=True,
    )
    locked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "n8n_thread_delivery_locks"
        indexes = [  # noqa: RUF012
            models.Index(fields=["locked_at"], name="idx_n8n_thread_lock_stale"),
        ]

    def __str__(self) -> str:
        return self.hubspot_thread_id


class HubSpotReconciliationCursor(models.Model):
    """Durable progress and lock metadata for one active HubSpot thread."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation_instance = models.OneToOneField(
        "ai_agents.ConversationInstance",
        on_delete=models.CASCADE,
        related_name="hubspot_reconciliation_cursor",
    )
    hubspot_thread_id = models.CharField(max_length=100, unique=True)
    last_message_id = models.CharField(max_length=255, blank=True, default="")
    last_message_created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hubspot_reconciliation_cursors"
        indexes = [  # noqa: RUF012
            models.Index(fields=["next_attempt_at", "locked_at"], name="idx_hs_reconcile_claim"),
        ]

    def __str__(self) -> str:
        return self.hubspot_thread_id


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
