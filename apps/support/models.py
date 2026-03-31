"""Models for support/helpdesk domain."""

from django.conf import settings
from django.db import models


class Queue(models.Model):
    """Support queue grouping related tickets."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "support_queues"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SLA(models.Model):
    """Service Level Agreement policy."""

    name = models.CharField(max_length=200)
    first_response_hours = models.PositiveSmallIntegerField(default=8)
    resolution_hours = models.PositiveSmallIntegerField(default=48)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "support_slas"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Ticket(models.Model):
    """Support ticket representing a customer issue."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        WAITING_CUSTOMER = "waiting_customer", "Waiting Customer"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        CHAT = "chat", "Chat"
        PHONE = "phone", "Phone"
        PORTAL = "portal", "Portal"

    hubspot_ticket_id = models.CharField(max_length=50, blank=True, unique=True, null=True, db_index=True)
    external_id = models.CharField(max_length=100, blank=True, db_index=True)
    subject = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.EMAIL)
    queue = models.ForeignKey(Queue, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    sla = models.ForeignKey(SLA, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    customer_email = models.EmailField(blank=True)
    customer_name = models.CharField(max_length=255, blank=True)
    church_external_id = models.CharField(max_length=100, blank=True, db_index=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    sla_breached = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_tickets"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["queue", "status"]),
        ]

    def __str__(self) -> str:
        return f"[{self.status}] {self.subject}"


class Agent(models.Model):
    """Support agent profile linked to a User."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_profile")
    queues = models.ManyToManyField(Queue, blank=True, related_name="agents")
    max_concurrent_tickets = models.PositiveSmallIntegerField(default=10)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_agents"

    def __str__(self) -> str:
        return str(self.user)


class Metric(models.Model):
    """Aggregated support metric snapshot."""

    date = models.DateField(db_index=True)
    queue = models.ForeignKey(Queue, on_delete=models.CASCADE, related_name="metrics")
    total_tickets = models.PositiveIntegerField(default=0)
    resolved_tickets = models.PositiveIntegerField(default=0)
    avg_first_response_hours = models.FloatField(default=0.0)
    avg_resolution_hours = models.FloatField(default=0.0)
    sla_breached_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "support_metrics"
        unique_together = [("date", "queue")]
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date} — {self.queue.name}"
