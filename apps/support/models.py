"""Models for support/helpdesk domain."""

from __future__ import annotations

import uuid

from django.db import models


class Queue(models.Model):
    """Support queue — maps to existing queue_settings table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "queue_settings"
        ordering = ["name"]  # noqa: RUF012

    def __str__(self) -> str:
        return self.name


class Agent(models.Model):
    """Support agent — maps to existing agents table in HelpdeskDB."""

    class StatusEnum(models.TextChoices):
        ONLINE = "online", "Online"
        AWAY = "away", "Away"
        OFFLINE = "offline", "Offline"
        BUSY = "busy", "Busy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    agent_email = models.TextField(unique=True)
    hubspot_owner_id = models.BigIntegerField()
    internal_user_id = models.BigIntegerField(null=True, blank=True)
    team = models.TextField(blank=True, null=True)
    manager_email = models.TextField(blank=True, null=True)
    status_enum = models.CharField(
        max_length=20,
        choices=StatusEnum.choices,
        default=StatusEnum.AWAY,
    )
    current_simultaneous_chats = models.BigIntegerField(default=0)
    max_simultaneous_chats = models.IntegerField(default=5)
    auto_assign_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(null=True, blank=True)
    working_hours = models.JSONField(null=True, blank=True)
    skills = models.JSONField(null=True, blank=True)
    timezone = models.TextField(default="America/Sao_Paulo")
    last_assignment_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "agents"
        ordering = ["name"]  # noqa: RUF012

    def __str__(self) -> str:
        return self.name


class Ticket(models.Model):
    """Support ticket — maps to existing tickets table in HelpdeskDB."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket_id = models.TextField(unique=True, db_index=True)
    customer_name = models.TextField(blank=True, null=True)
    ticket_church = models.TextField(blank=True, null=True, db_index=True)
    category = models.TextField(blank=True, null=True)
    priority = models.TextField(blank=True, null=True, db_index=True)
    status = models.TextField(blank=True, null=True, db_index=True)
    affected_device = models.TextField(blank=True, null=True)
    scope_of_impact = models.TextField(blank=True, null=True)
    affected_module = models.TextField(blank=True, null=True)
    affected_functionality = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    inserted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets"
        ordering = ["-created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["ticket_church", "status"]),
        ]

    def __str__(self) -> str:
        return f"[{self.status}] {self.ticket_id}"


class AgentStatusHistory(models.Model):
    """Agent status change audit trail."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="status_history", db_column="agent_id")
    old_status = models.CharField(max_length=20, blank=True, null=True)
    new_status = models.CharField(max_length=20)
    changed_at = models.DateTimeField(auto_now_add=True)
    sync_source = models.TextField(default="internal")
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "agent_status_history"
        ordering = ["-changed_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.agent.name}: {self.old_status} → {self.new_status}"


class AgentMetrics(models.Model):
    """Per-agent aggregated metrics."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_id = models.BigIntegerField(db_index=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    average_online_time = models.FloatField(default=0.0)
    average_away_time = models.FloatField(default=0.0)
    average_daily_tickets = models.BigIntegerField(default=0)
    average_response_time_min = models.FloatField(default=0.0)
    average_ticket_time_min = models.FloatField(default=0.0)
    tickets_transfer = models.BigIntegerField(default=0)
    csat = models.BigIntegerField(default=0)
    total_chats = models.IntegerField(default=0)
    chats_closed = models.IntegerField(default=0)
    first_response_time_avg_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    resolution_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    customer_satisfaction_avg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    last_time_updated = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "agent_metrics"
        ordering = ["-last_time_updated"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"Metrics agent_id={self.agent_id} ({self.period_start}-{self.period_end})"


class TicketJiraAssociation(models.Model):
    """Links a ticket to a Jira issue."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="jira_associations", db_column="ticket_id"
    )
    jira_issue_id = models.UUIDField(db_index=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    association_active = models.BooleanField(default=True)

    class Meta:
        db_table = "ticket_jira_associations"

    def __str__(self) -> str:
        return f"{self.ticket_id} ↔ {self.jira_issue_id}"


# ---------------------------------------------------------------------------
# Auto-assignment queue models
# ---------------------------------------------------------------------------


class NewConversation(models.Model):
    """Ticket that entered the NOVO stage and is awaiting automatic assignment.

    Maps to the ``new_conversations`` table in Supabase.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_ticket_id = models.TextField(unique=True, db_index=True)
    pipeline_id = models.TextField(default="636459134")
    contact_name = models.TextField(blank=True, null=True)
    contact_email = models.TextField(blank=True, null=True)
    priority = models.TextField(blank=True, null=True)
    subject = models.TextField(blank=True, null=True)
    entered_queue_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "new_conversations"
        ordering = ["entered_queue_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"NewConversation {self.hubspot_ticket_id}"


class AssignedConversation(models.Model):
    """Ticket that has been assigned to an agent by the auto-assignment system.

    Maps to the ``assigned_conversations`` table in Supabase.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_ticket_id = models.TextField(unique=True, db_index=True)
    agent = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_conversations",
        db_column="agent_id",
    )
    hubspot_owner_id = models.BigIntegerField(db_index=True)
    agent_name = models.TextField()
    pipeline_id = models.TextField(default="636459134")
    entered_queue_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(db_index=True)
    queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    closed_by_owner_id = models.BigIntegerField(null=True, blank=True)
    closed_by_agent_name = models.TextField(null=True, blank=True)
    total_handle_time_minutes = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    contact_name = models.TextField(null=True, blank=True)
    contact_email = models.TextField(null=True, blank=True)
    priority = models.TextField(null=True, blank=True)
    subject = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assigned_conversations"
        ordering = ["-assigned_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["hubspot_owner_id", "assigned_at"]),
            models.Index(fields=["assigned_at"]),
        ]

    def __str__(self) -> str:
        return f"AssignedConversation {self.hubspot_ticket_id} → {self.agent_name}"


class ClosedConversation(models.Model):
    """Ticket that was closed after being handled by an agent.

    Records are moved here from ``assigned_conversations`` (or directly from
    ``new_conversations`` if the ticket was closed before assignment) when a
    closure event arrives from HubSpot.

    Maps to the ``closed_conversations`` table in Supabase.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_ticket_id = models.TextField(unique=True, db_index=True)
    agent = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_conversations",
        db_column="agent_id",
    )
    hubspot_owner_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    agent_name = models.TextField(null=True, blank=True)
    pipeline_id = models.TextField(default="636459134")
    entered_queue_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(db_index=True)
    closed_by_owner_id = models.BigIntegerField(null=True, blank=True)
    closed_by_agent_name = models.TextField(null=True, blank=True)
    queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_handle_time_minutes = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    contact_name = models.TextField(null=True, blank=True)
    contact_email = models.TextField(null=True, blank=True)
    priority = models.TextField(null=True, blank=True)
    subject = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "closed_conversations"
        ordering = ["-closed_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["closed_at"]),
            models.Index(fields=["hubspot_owner_id", "closed_at"]),
        ]

    def __str__(self) -> str:
        return f"ClosedConversation {self.hubspot_ticket_id} closed_at={self.closed_at}"


class QueuePerformanceMetrics(models.Model):
    """Daily aggregated metrics for the automatic assignment queue.

    Maps to the ``queue_performance_metrics`` table in Supabase.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    metric_date = models.DateField(unique=True, db_index=True)
    total_entered_queue = models.IntegerField(default=0)
    total_assigned = models.IntegerField(default=0)
    total_closed = models.IntegerField(default=0)
    avg_queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    min_queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    p50_queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    p95_queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    avg_handle_time_minutes = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    assignments_by_agent = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "queue_performance_metrics"
        ordering = ["-metric_date"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"QueueMetrics {self.metric_date} (assigned={self.total_assigned})"


class AssignmentLog(models.Model):
    """Log entry for each assignment action performed by the queue system.

    Maps to the existing ``assignment_logs`` table in Supabase, extended with
    queue-specific columns.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket_id = models.TextField(db_index=True)
    agent = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignment_logs",
        db_column="agent_id",
    )
    agent_name = models.TextField()
    hubspot_owner_id = models.BigIntegerField(null=True, blank=True)
    assignment_type = models.TextField(default="automatic")
    assigned_by = models.TextField(null=True, blank=True)
    pipeline_id = models.TextField(null=True, blank=True)
    entered_queue_at = models.DateTimeField(null=True, blank=True)
    queue_wait_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assignment_logs"
        ordering = ["-assigned_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"AssignmentLog ticket={self.ticket_id} → {self.agent_name}"
