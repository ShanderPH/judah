"""Models for AI agents domain."""

from django.db import models


class AgentSession(models.Model):
    """Represents a conversation session with an AI agent."""

    class AgentType(models.TextChoices):
        SALOMAO = "salomao", "Salomão"
        HEIMDALL = "heimdall", "Heimdall"

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
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.agent_type} — {self.session_id}"


class AgentMemory(models.Model):
    """Persisted memory entry for an agent session."""

    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name="memories")
    key = models.CharField(max_length=200)
    value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_memories"
        unique_together = [("session", "key")]

    def __str__(self) -> str:
        return f"{self.session.session_id} — {self.key}"


class AgentTrace(models.Model):
    """Execution trace for a single agent turn (request/response pair)."""

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
        ordering = ["session", "created_at"]

    def __str__(self) -> str:
        return f"{self.session.session_id} — {self.role}"
