"""Models for AI agents domain."""

import uuid
from decimal import Decimal

from django.db import models


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
