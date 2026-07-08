"""Models for AI agents domain."""

import uuid
from decimal import Decimal

from django.db import models
from django.db.models import Q


class AgentSession(models.Model):
    """Represents a conversation session with an AI agent."""

    class AgentType(models.TextChoices):
        SALOMAO = "salomao", "Salomão"
        HEIMDALL = "heimdall", "Heimdall"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_id = models.CharField(max_length=100, unique=True, db_index=True)
    agent_type = models.CharField(max_length=20, choices=AgentType.choices, default=AgentType.SALOMAO)
    user_identifier = models.CharField(max_length=255, blank=True, db_index=True)
    channel = models.CharField(max_length=50, blank=True)
    hubspot_contact_id = models.CharField(max_length=50, blank=True, db_index=True)
    church_external_id = models.CharField(max_length=100, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_sessions"
        ordering = ["-created_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.agent_type} — {self.session_id}"


class AgentMemory(models.Model):
    """Persisted memory entry for an agent session."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name="memories")
    key = models.CharField(max_length=200)
    value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_memories"
        unique_together = [("session", "key")]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.session.session_id} — {self.key}"


class AgentTrace(models.Model):
    """Execution trace for a single agent turn (request/response pair)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        TOOL = "tool", "Tool"

    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name="traces")
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    tool_name = models.CharField(max_length=100, blank=True)
    tool_input = models.JSONField(null=True, blank=True)
    tool_output = models.JSONField(null=True, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "agent_traces"
        ordering = ["session", "created_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.session.session_id} — {self.role}"


class TokenTrackingLog(models.Model):
    """Registro de consumo de tokens e custo por execução do pipeline.

    Alimentado ao fim de cada `run_pipeline_async()` do Supervisor para que o
    time de FinOps consiga agregar custo por ticket/sessão/modelo. Decimal
    com 6 casas é suficiente para representar frações de centavo em modelos
    pequenos (gpt-4o-mini: $0.15 / 1M tokens ≈ $1.5e-7 por token).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_id = models.CharField(max_length=100, db_index=True)
    ticket_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    model_name = models.CharField(max_length=100)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal("0"),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "token_tracking_logs"
        ordering = ["-created_at"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.session_id} — {self.model_name} — ${self.total_cost_usd}"


class ConversationInstance(models.Model):
    """Persisted state machine instance for a HubSpot/customer conversation."""

    class State(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        NORMALIZED = "NORMALIZED", "Normalized"
        CONTEXT_HYDRATING = "CONTEXT_HYDRATING", "Context Hydrating"
        CONTEXT_READY = "CONTEXT_READY", "Context Ready"
        CONTACT_REQUIRED = "CONTACT_REQUIRED", "Contact Required"
        CONTACT_COLLECTING = "CONTACT_COLLECTING", "Contact Collecting"
        CONTACT_ASSOCIATING = "CONTACT_ASSOCIATING", "Contact Associating"
        TRIAGE_PENDING = "TRIAGE_PENDING", "Triage Pending"
        TRIAGE_RUNNING = "TRIAGE_RUNNING", "Triage Running"
        AI_SERVICE_PENDING = "AI_SERVICE_PENDING", "AI Service Pending"
        AI_SERVICE_RUNNING = "AI_SERVICE_RUNNING", "AI Service Running"
        HUMAN_HANDOFF_REQUESTED = "HUMAN_HANDOFF_REQUESTED", "Human Handoff Requested"
        QUEUE_PENDING = "QUEUE_PENDING", "Queue Pending"
        HUMAN_ASSIGNED = "HUMAN_ASSIGNED", "Human Assigned"
        HUMAN_IN_PROGRESS = "HUMAN_IN_PROGRESS", "Human In Progress"
        RESOLVED_BY_AI = "RESOLVED_BY_AI", "Resolved by AI"
        RESOLVED_BY_HUMAN = "RESOLVED_BY_HUMAN", "Resolved by Human"
        CLOSED = "CLOSED", "Closed"
        FAILED_RETRYABLE = "FAILED_RETRYABLE", "Failed Retryable"
        FAILED_TERMINAL = "FAILED_TERMINAL", "Failed Terminal"
        IGNORED = "IGNORED", "Ignored"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hubspot_thread_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    hubspot_ticket_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    hubspot_contact_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    channel = models.CharField(max_length=50, blank=True, db_index=True)
    pipeline_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    pipeline_stage_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    state = models.CharField(max_length=40, choices=State.choices, default=State.RECEIVED, db_index=True)
    state_version = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=255, unique=True)
    last_event_id = models.CharField(max_length=255, blank=True)
    last_message_id = models.CharField(max_length=255, blank=True)
    assigned_agent_id = models.CharField(max_length=100, null=True, blank=True)
    ai_session_id = models.CharField(max_length=100, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    current_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversation_instances"
        ordering = ["-last_activity_at", "-created_at"]  # noqa: RUF012
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["hubspot_thread_id"],
                condition=Q(hubspot_thread_id__isnull=False) & ~Q(hubspot_thread_id=""),
                name="unique_conversation_instance_thread",
            ),
            models.UniqueConstraint(
                fields=["hubspot_ticket_id"],
                condition=Q(hubspot_ticket_id__isnull=False) & ~Q(hubspot_ticket_id=""),
                name="unique_conversation_instance_ticket",
            ),
        ]
        indexes = [  # noqa: RUF012
            models.Index(fields=["state", "last_activity_at"], name="idx_conv_state_activity"),
            models.Index(fields=["channel", "state"], name="idx_conv_channel_state"),
        ]

    def __str__(self) -> str:
        target = self.hubspot_thread_id or self.hubspot_ticket_id or str(self.id)
        return f"{target} [{self.state}]"


class ConversationEvent(models.Model):
    """Append-only normalized event linked to a conversation instance."""

    class ProcessingStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSED = "PROCESSED", "Processed"
        DUPLICATE = "DUPLICATE", "Duplicate"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(ConversationInstance, on_delete=models.CASCADE, related_name="events")
    source = models.CharField(max_length=50, db_index=True)
    source_event_id = models.CharField(max_length=255, blank=True, db_index=True)
    event_type = models.CharField(max_length=100, db_index=True)
    occurred_at = models.DateTimeField(null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "conversation_events"
        ordering = ["created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["instance", "event_type"], name="idx_conv_event_type"),
            models.Index(fields=["source", "source_event_id"], name="idx_conv_event_source"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} / {self.instance_id}"


class ConversationStateTransition(models.Model):
    """Append-only audit trail for state machine transitions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(ConversationInstance, on_delete=models.CASCADE, related_name="state_transitions")
    from_state = models.CharField(max_length=40, blank=True)
    to_state = models.CharField(max_length=40, choices=ConversationInstance.State.choices, db_index=True)
    reason = models.TextField()
    actor_type = models.CharField(max_length=50, default="system")
    actor_id = models.CharField(max_length=100, blank=True)
    source_event_id = models.CharField(max_length=255, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "conversation_state_transitions"
        ordering = ["created_at"]  # noqa: RUF012
        indexes = [models.Index(fields=["instance", "created_at"], name="idx_conv_transition_time")]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.from_state or 'START'} -> {self.to_state}"


class AgentRun(models.Model):
    """Persisted audit record for a single agent/model execution."""

    class Status(models.TextChoices):
        STARTED = "STARTED", "Started"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(
        ConversationInstance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )
    agent_name = models.CharField(max_length=100, db_index=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    output_structured = models.JSONField(default=dict, blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED, db_index=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "agent_runs"
        ordering = ["-created_at"]  # noqa: RUF012
        indexes = [models.Index(fields=["instance", "agent_name"], name="idx_agent_run_instance")]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.agent_name} [{self.status}]"


class ToolCallAuditLog(models.Model):
    """Audit log for external or stateful tool calls."""

    class Status(models.TextChoices):
        STARTED = "STARTED", "Started"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(ConversationInstance, on_delete=models.CASCADE, related_name="tool_call_audits")
    agent_run = models.ForeignKey(
        AgentRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tool_call_audits",
    )
    tool_name = models.CharField(max_length=100, db_index=True)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED, db_index=True)
    external_object_type = models.CharField(max_length=100, blank=True)
    external_object_id = models.CharField(max_length=255, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tool_call_audit_logs"
        ordering = ["-created_at"]  # noqa: RUF012
        indexes = [models.Index(fields=["instance", "tool_name"], name="idx_tool_audit_instance")]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.tool_name} [{self.status}]"
