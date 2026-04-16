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
    total_assignments = models.IntegerField(default=0)
    online_time_seconds_today = models.IntegerField(default=0)
    away_time_seconds_today = models.IntegerField(default=0)
    last_status_change_at = models.DateTimeField(null=True, blank=True)
    sat_last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    sat_last_count_sync_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "agents"
        ordering = ["name"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["status_enum", "auto_assign_enabled"], name="idx_agent_eligible"),
            models.Index(fields=["hubspot_owner_id"], name="idx_agent_hubspot_owner"),
        ]

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

    Queue position is determined by ``entered_queue_at`` (FIFO order).
    Tickets that cannot be assigned immediately remain in this table until
    an agent becomes available, at which point ``assign_pending_tickets()``
    processes them in order.
    """

    class QueueStatus(models.TextChoices):
        PENDING = "pending", "Pending Assignment"
        QUEUED = "queued", "In Queue (No Agent Available)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_ticket_id = models.TextField(unique=True, db_index=True)
    pipeline_id = models.TextField(default="636459134")
    contact_name = models.TextField(blank=True, null=True)
    contact_email = models.TextField(blank=True, null=True)
    priority = models.TextField(blank=True, null=True)
    subject = models.TextField(blank=True, null=True)
    entered_queue_at = models.DateTimeField(db_index=True)
    queue_status = models.CharField(
        max_length=20,
        choices=QueueStatus.choices,
        default=QueueStatus.PENDING,
    )
    assignment_attempts = models.IntegerField(default=0)
    last_assignment_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "new_conversations"
        ordering = ["entered_queue_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"NewConversation {self.hubspot_ticket_id}"

    @property
    def queue_position(self) -> int:
        """Calculate the current position in the queue (1-indexed).

        Position is based on ``entered_queue_at`` ordering (oldest = position 1).
        """
        return NewConversation.objects.filter(entered_queue_at__lt=self.entered_queue_at).count() + 1


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
    assignment_count = models.IntegerField(default=1)
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
    resolution_time_minutes = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    closure_source = models.CharField(max_length=20, default="agent")
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
        indexes = [  # noqa: RUF012
            models.Index(fields=["assignment_type", "-assigned_at"], name="idx_alog_type_assigned_desc"),
        ]

    def __str__(self) -> str:
        return f"AssignmentLog ticket={self.ticket_id} → {self.agent_name}"


class ConversationReassignment(models.Model):
    """Tracks when a ticket is transferred from one agent to another.

    This captures manual reassignments done by agents in HubSpot, enabling:
    - Accurate conversation count per agent (decrement source, increment target)
    - Metrics on ticket routing paths
    - Identification of tickets that required escalation or transfer

    Maps to the ``conversation_reassignments`` table in Supabase.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_ticket_id = models.TextField(db_index=True)
    from_agent = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassignments_from",
        db_column="from_agent_id",
    )
    from_hubspot_owner_id = models.BigIntegerField(null=True, blank=True)
    from_agent_name = models.TextField(null=True, blank=True)
    to_agent = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassignments_to",
        db_column="to_agent_id",
    )
    to_hubspot_owner_id = models.BigIntegerField(null=True, blank=True)
    to_agent_name = models.TextField(null=True, blank=True)
    reassigned_at = models.DateTimeField(db_index=True)
    time_with_previous_agent_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    reassignment_source = models.TextField(default="hubspot_webhook")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conversation_reassignments"
        ordering = ["-reassigned_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["hubspot_ticket_id", "reassigned_at"]),
            models.Index(fields=["from_hubspot_owner_id", "reassigned_at"]),
            models.Index(fields=["to_hubspot_owner_id", "reassigned_at"]),
        ]

    def __str__(self) -> str:
        return f"Reassignment {self.hubspot_ticket_id}: {self.from_agent_name} → {self.to_agent_name}"


class BusinessHoursConfig(models.Model):
    """Configurable business hours for the SAT system.

    When active, overrides the hardcoded BUSINESS_HOURS dictionary in
    ``agent_sync_service.py``. Only one active config should exist at a time
    (enforced by ``is_active`` flag).

    Maps to the ``business_hours_config`` table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, default="default")
    is_active = models.BooleanField(default=True)
    monday_start = models.IntegerField(default=9)
    monday_end = models.IntegerField(default=18)
    tuesday_start = models.IntegerField(default=9)
    tuesday_end = models.IntegerField(default=18)
    wednesday_start = models.IntegerField(default=9)
    wednesday_end = models.IntegerField(default=18)
    thursday_start = models.IntegerField(default=9)
    thursday_end = models.IntegerField(default=18)
    friday_start = models.IntegerField(default=9)
    friday_end = models.IntegerField(default=18)
    saturday_start = models.IntegerField(default=9)
    saturday_end = models.IntegerField(default=13)
    sunday_start = models.IntegerField(default=8)
    sunday_end = models.IntegerField(default=12)
    timezone_name = models.CharField(max_length=50, default="America/Sao_Paulo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "business_hours_config"

    def __str__(self) -> str:
        return f"BusinessHours '{self.name}' (active={self.is_active})"

    def get_hours_for_weekday(self, weekday: int) -> tuple[int, int] | None:
        """Return (start_hour, end_hour) for a given weekday (0=Monday)."""
        mapping = {
            0: (self.monday_start, self.monday_end),
            1: (self.tuesday_start, self.tuesday_end),
            2: (self.wednesday_start, self.wednesday_end),
            3: (self.thursday_start, self.thursday_end),
            4: (self.friday_start, self.friday_end),
            5: (self.saturday_start, self.saturday_end),
            6: (self.sunday_start, self.sunday_end),
        }
        hours = mapping.get(weekday)
        if hours and hours[0] >= hours[1]:
            return None  # Invalid or disabled (start >= end)
        return hours


class SpecialSchedule(models.Model):
    """Override business hours for a specific date.

    Used for holidays, special events, or ad-hoc schedule changes.
    Takes precedence over ``BusinessHoursConfig`` for the specified date.

    Maps to the ``special_schedules`` table.
    """

    class ScheduleType(models.TextChoices):
        CLOSED = "closed", "Closed (no operation)"
        CUSTOM = "custom", "Custom hours"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField(unique=True, db_index=True)
    schedule_type = models.CharField(
        max_length=20,
        choices=ScheduleType.choices,
        default=ScheduleType.CLOSED,
    )
    start_hour = models.IntegerField(null=True, blank=True)
    end_hour = models.IntegerField(null=True, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "special_schedules"
        ordering = ["-date"]  # noqa: RUF012

    def __str__(self) -> str:
        if self.schedule_type == self.ScheduleType.CLOSED:
            return f"SpecialSchedule {self.date} — CLOSED ({self.reason})"
        return f"SpecialSchedule {self.date} — {self.start_hour}h-{self.end_hour}h ({self.reason})"


class AgentDailyTimeLog(models.Model):
    """Daily accumulated online/away time per agent.

    Populated by the SAT (Smart Agent Tracking) service at midnight
    when daily counters on the Agent model are snapshotted and reset.

    Maps to the ``agent_daily_time_logs`` table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        related_name="daily_time_logs",
        db_column="agent_id",
    )
    log_date = models.DateField(db_index=True)
    online_time_seconds = models.IntegerField(default=0)
    away_time_seconds = models.IntegerField(default=0)
    status_transitions = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_daily_time_logs"
        ordering = ["-log_date"]  # noqa: RUF012
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(fields=["agent", "log_date"], name="unique_agent_daily_log"),
        ]

    def __str__(self) -> str:
        return f"TimeLog {self.agent.name} {self.log_date} (online={self.online_time_seconds}s)"
