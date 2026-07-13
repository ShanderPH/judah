"""Deterministic lifecycle engine for helpdesk/AI conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.ai_agents.models import (
    AgentRun,
    ConversationEvent,
    ConversationInstance,
    ConversationStateTransition,
    ToolCallAuditLog,
)
from apps.ai_agents.services.channel_capabilities import can_send_automated_reply, normalize_channel

logger = structlog.get_logger(__name__)

RouteName = Literal[
    "IGNORE",
    "AUTO_ASSIGNMENT",
    "AI_TRIAGE",
    "AI_SERVICE",
    "HUMAN_HANDOFF",
    "CLOSE",
    "WAIT_FOR_CONTACT_DATA",
]

_STAGE_NOVO_ID = settings.HUBSPOT_SUPPORT_NEW_STAGE_ID
_STAGE_FECHADO_ID = settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID
_PROP_STAGE_NOVO = f"hs_v2_date_entered_{_STAGE_NOVO_ID}"
_PROP_STAGE_CLOSED = f"hs_v2_date_entered_{_STAGE_FECHADO_ID}"
_PROP_PIPELINE_STAGE = "hs_pipeline_stage"
_PROP_OWNER_ID = "hubspot_owner_id"
_REQUIRED_LIFECYCLE_TABLES = {
    "conversation_instances",
    "conversation_events",
    "conversation_state_transitions",
    "agent_runs",
    "tool_call_audit_logs",
}


class InvalidStateTransitionError(ValueError):
    """Raised when a lifecycle transition is not allowed."""


def is_lifecycle_schema_ready() -> bool:
    """Return whether lifecycle tables exist in the current database."""
    try:
        existing_tables = set(connection.introspection.table_names())
    except Exception as exc:
        logger.warning(
            "lifecycle_schema_check_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False
    return _REQUIRED_LIFECYCLE_TABLES.issubset(existing_tables)


@dataclass(frozen=True)
class NormalizedEvent:
    """Provider-neutral event generated from an external webhook."""

    source: str
    source_event_id: str
    event_type: str
    idempotency_key: str
    payload: dict[str, Any]
    occurred_at: datetime | None = None
    hubspot_thread_id: str | None = None
    hubspot_ticket_id: str | None = None
    hubspot_contact_id: str | None = None
    channel: str = "unknown"
    direction: str = ""
    pipeline_id: str | None = None
    pipeline_stage_id: str | None = None
    message_id: str = ""


@dataclass(frozen=True)
class RouteDecision:
    """Deterministic routing decision before any LLM runs."""

    route: RouteName
    target_state: str
    reason: str
    can_send_reply: bool = True


@dataclass(frozen=True)
class LifecycleRecordResult:
    """Result of recording an external event into the lifecycle ledger."""

    instance: ConversationInstance
    event: ConversationEvent
    decision: RouteDecision
    event_created: bool


TERMINAL_STATES = {
    ConversationInstance.State.CLOSED,
    ConversationInstance.State.FAILED_TERMINAL,
    ConversationInstance.State.IGNORED,
}

ACTIVE_STATES = {state for state, _label in ConversationInstance.State.choices} - TERMINAL_STATES

VALID_TRANSITIONS: dict[str, set[str]] = {
    ConversationInstance.State.RECEIVED: {
        ConversationInstance.State.NORMALIZED,
        ConversationInstance.State.IGNORED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.NORMALIZED: {
        ConversationInstance.State.CONTEXT_HYDRATING,
        ConversationInstance.State.QUEUE_PENDING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.RESOLVED_BY_HUMAN,
        ConversationInstance.State.CLOSED,
        ConversationInstance.State.IGNORED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.CONTEXT_HYDRATING: {
        ConversationInstance.State.CONTEXT_READY,
        ConversationInstance.State.CONTACT_REQUIRED,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.CONTEXT_READY: {
        ConversationInstance.State.CONTACT_REQUIRED,
        ConversationInstance.State.TRIAGE_PENDING,
        ConversationInstance.State.AI_SERVICE_PENDING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.QUEUE_PENDING,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.CONTACT_REQUIRED: {
        ConversationInstance.State.CONTACT_COLLECTING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.CONTACT_COLLECTING: {
        ConversationInstance.State.CONTACT_ASSOCIATING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.CONTACT_ASSOCIATING: {
        ConversationInstance.State.CONTEXT_READY,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.TRIAGE_PENDING: {
        ConversationInstance.State.TRIAGE_RUNNING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.TRIAGE_RUNNING: {
        ConversationInstance.State.AI_SERVICE_PENDING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.QUEUE_PENDING,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.AI_SERVICE_PENDING: {
        ConversationInstance.State.AI_SERVICE_RUNNING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.AI_SERVICE_RUNNING: {
        ConversationInstance.State.RESOLVED_BY_AI,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.HUMAN_HANDOFF_REQUESTED: {
        ConversationInstance.State.QUEUE_PENDING,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.QUEUE_PENDING: {
        ConversationInstance.State.HUMAN_ASSIGNED,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.HUMAN_ASSIGNED: {
        ConversationInstance.State.HUMAN_IN_PROGRESS,
        ConversationInstance.State.RESOLVED_BY_HUMAN,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.HUMAN_IN_PROGRESS: {
        ConversationInstance.State.RESOLVED_BY_HUMAN,
        ConversationInstance.State.FAILED_RETRYABLE,
    },
    ConversationInstance.State.RESOLVED_BY_AI: {ConversationInstance.State.CLOSED},
    ConversationInstance.State.RESOLVED_BY_HUMAN: {ConversationInstance.State.CLOSED},
    ConversationInstance.State.FAILED_RETRYABLE: {
        ConversationInstance.State.CONTEXT_HYDRATING,
        ConversationInstance.State.TRIAGE_PENDING,
        ConversationInstance.State.AI_SERVICE_PENDING,
        ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        ConversationInstance.State.FAILED_TERMINAL,
    },
}


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _parse_hubspot_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except TypeError, ValueError, OSError:
        return None


def _event_id_from_payload(payload: dict[str, Any]) -> str:
    return _as_text(payload.get("eventId") or payload.get("event_id"))


def _message_id_from_payload(payload: dict[str, Any]) -> str:
    return _as_text(payload.get("messageId") or payload.get("message_id") or payload.get("id"))


def _thread_id_from_payload(payload: dict[str, Any]) -> str | None:
    value = (
        payload.get("threadId")
        or payload.get("conversationThreadId")
        or payload.get("conversationsThreadId")
        or payload.get("thread_id")
    )
    return _as_text(value) or None


def _idempotency_key(
    *,
    source: str,
    event_type: str,
    object_id: str,
    occurred_at: str,
    source_event_id: str,
    message_id: str,
) -> str:
    natural_id = source_event_id or f"{object_id}:{occurred_at}:{message_id}"
    return f"{source}:{event_type}:{natural_id}"


class EventNormalizer:
    """Convert raw webhook rows into provider-neutral lifecycle events."""

    def normalize_webhook_event(self, event: Any, *, source: str = "hubspot") -> NormalizedEvent:
        payload: dict[str, Any] = dict(getattr(event, "payload", {}) or {})
        raw_event_type = _as_text(getattr(event, "event_type", "") or payload.get("subscriptionType") or "unknown")
        object_id = _as_text(payload.get("objectId") or payload.get("object_id") or getattr(event, "object_id", ""))
        property_name = _as_text(payload.get("propertyName") or payload.get("property_name"))
        property_value = _as_text(payload.get("propertyValue") or payload.get("property_value"))
        source_event_id = _event_id_from_payload(payload) or _as_text(getattr(event, "id", ""))
        message_id = _message_id_from_payload(payload)
        occurred_at_raw = _as_text(payload.get("occurredAt") or payload.get("occurred_at"))
        occurred_at = _parse_hubspot_timestamp(occurred_at_raw)
        direction = _as_text(payload.get("direction") or payload.get("messageDirection")).upper()
        channel = normalize_channel(
            payload.get("channel")
            or payload.get("channelType")
            or payload.get("messageType")
            or payload.get("source")
            or payload.get("sourceType")
        )

        normalized_type = raw_event_type
        hubspot_ticket_id: str | None = None
        hubspot_thread_id: str | None = None
        pipeline_stage_id: str | None = None

        if raw_event_type == "conversation.newMessage":
            normalized_type = "conversation_message_received"
            hubspot_thread_id = _thread_id_from_payload(payload) or object_id or None
        elif raw_event_type == "ticket.propertyChange":
            hubspot_ticket_id = object_id or None
            if property_name == _PROP_STAGE_NOVO:
                normalized_type = "ticket_entered_n1"
                pipeline_stage_id = _STAGE_NOVO_ID
            elif property_name == _PROP_STAGE_CLOSED:
                normalized_type = "ticket_closed"
                pipeline_stage_id = _STAGE_FECHADO_ID
            elif property_name == _PROP_OWNER_ID:
                normalized_type = "owner_changed"
            elif property_name == _PROP_PIPELINE_STAGE:
                pipeline_stage_id = property_value or None
                normalized_type = "ticket_closed" if property_value == _STAGE_FECHADO_ID else "ticket_stage_changed"
        elif raw_event_type in {"ticket.creation", "ticket.created"}:
            normalized_type = "ticket_created"
            hubspot_ticket_id = object_id or None
        elif raw_event_type.startswith("ticket."):
            hubspot_ticket_id = object_id or None
        elif raw_event_type.startswith("contact."):
            normalized_type = "contact_association_changed"

        idempotency_key = _idempotency_key(
            source=source,
            event_type=raw_event_type,
            object_id=object_id,
            occurred_at=occurred_at_raw,
            source_event_id=source_event_id,
            message_id=message_id,
        )

        return NormalizedEvent(
            source=source,
            source_event_id=source_event_id,
            event_type=normalized_type,
            idempotency_key=idempotency_key,
            payload=payload,
            occurred_at=occurred_at,
            hubspot_thread_id=hubspot_thread_id,
            hubspot_ticket_id=hubspot_ticket_id,
            hubspot_contact_id=_as_text(payload.get("contactId") or payload.get("contact_id")) or None,
            channel=channel,
            direction=direction,
            pipeline_id=_as_text(payload.get("pipelineId") or payload.get("pipeline_id")) or None,
            pipeline_stage_id=pipeline_stage_id,
            message_id=message_id,
        )


class RoutingPolicyEngine:
    """Deterministic policy router that runs before any agent."""

    def route(self, event: NormalizedEvent) -> RouteDecision:
        can_reply = can_send_automated_reply(event.channel)

        if event.direction and event.direction != "INCOMING":
            return RouteDecision(
                route="IGNORE",
                target_state=ConversationInstance.State.IGNORED,
                reason="Non-incoming conversation message.",
                can_send_reply=can_reply,
            )

        if event.event_type == "ticket_closed":
            return RouteDecision(
                route="CLOSE",
                target_state=ConversationInstance.State.CLOSED,
                reason="HubSpot ticket closed.",
                can_send_reply=can_reply,
            )

        if event.event_type == "ticket_entered_n1":
            return RouteDecision(
                route="AUTO_ASSIGNMENT",
                target_state=ConversationInstance.State.QUEUE_PENDING,
                reason="Ticket entered the support N1 assignment stage.",
                can_send_reply=can_reply,
            )

        triage_pipeline_id = getattr(settings, "HUBSPOT_AI_TRIAGE_PIPELINE_ID", "")
        triage_new_stage_id = getattr(settings, "HUBSPOT_N1_NEW_STAGE_ID", "")
        triage_stage_id = getattr(settings, "HUBSPOT_AI_TRIAGE_STAGE_ID", "")
        triage_closed_stage_id = getattr(settings, "HUBSPOT_CLOSED_STAGE_ID", "")
        belongs_to_triage_pipeline = (
            not triage_pipeline_id or not event.pipeline_id or event.pipeline_id == triage_pipeline_id
        )
        if (
            event.event_type == "ticket_stage_changed"
            and belongs_to_triage_pipeline
            and triage_closed_stage_id
            and event.pipeline_stage_id == triage_closed_stage_id
        ):
            return RouteDecision(
                route="CLOSE",
                target_state=ConversationInstance.State.CLOSED,
                reason="Ticket entered the configured AI triage closed stage.",
                can_send_reply=can_reply,
            )

        if (
            event.event_type == "ticket_stage_changed"
            and belongs_to_triage_pipeline
            and event.pipeline_stage_id in {triage_new_stage_id, triage_stage_id}
            and event.pipeline_stage_id
        ):
            return RouteDecision(
                route="AI_TRIAGE",
                target_state=ConversationInstance.State.CONTEXT_HYDRATING,
                reason="Ticket entered a configured AI triage stage.",
                can_send_reply=can_reply,
            )

        if event.event_type == "conversation_message_received":
            if not can_reply:
                return RouteDecision(
                    route="HUMAN_HANDOFF",
                    target_state=ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
                    reason=f"Channel {event.channel} does not allow automated replies.",
                    can_send_reply=False,
                )
            return RouteDecision(
                route="AI_TRIAGE",
                target_state=ConversationInstance.State.CONTEXT_HYDRATING,
                reason="Incoming HubSpot conversation message.",
                can_send_reply=True,
            )

        return RouteDecision(
            route="IGNORE",
            target_state=ConversationInstance.State.IGNORED,
            reason="No lifecycle policy matched this event.",
            can_send_reply=can_reply,
        )


class LifecycleEngine:
    """State machine plus append-only event/transition ledger."""

    def record_normalized_event(
        self,
        event: NormalizedEvent,
        *,
        decision: RouteDecision | None = None,
    ) -> LifecycleRecordResult:
        decision = decision or RoutingPolicyEngine().route(event)
        with transaction.atomic():
            instance, _instance_created = self._get_or_create_instance(event)
            self._refresh_instance_snapshot(instance, event)
            lifecycle_event, event_created = self._append_event(instance, event)
            if event_created:
                if instance.state == ConversationInstance.State.RECEIVED:
                    self.transition(
                        instance,
                        ConversationInstance.State.NORMALIZED,
                        reason="External event normalized.",
                        source_event_id=event.source_event_id,
                    )
                self.transition(
                    instance,
                    decision.target_state,
                    reason=decision.reason,
                    source_event_id=event.source_event_id,
                )
            else:
                lifecycle_event.processing_status = ConversationEvent.ProcessingStatus.DUPLICATE
                lifecycle_event.save(update_fields=["processing_status"])

        return LifecycleRecordResult(
            instance=instance,
            event=lifecycle_event,
            decision=decision,
            event_created=event_created,
        )

    def transition(
        self,
        instance: ConversationInstance,
        to_state: str,
        *,
        reason: str,
        actor_type: str = "system",
        actor_id: str = "",
        source_event_id: str = "",
        allow_terminal_reopen: bool = False,
    ) -> ConversationInstance:
        if instance.state == to_state:
            return instance
        self._validate_transition(instance.state, to_state, allow_terminal_reopen=allow_terminal_reopen)
        now = timezone.now()
        from_state = instance.state
        instance.state = to_state
        instance.state_version += 1
        instance.last_activity_at = now
        if to_state == ConversationInstance.State.CLOSED and instance.closed_at is None:
            instance.closed_at = now
        instance.save(update_fields=["state", "state_version", "last_activity_at", "closed_at", "updated_at"])
        ConversationStateTransition.objects.create(
            instance=instance,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_event_id=source_event_id,
        )
        logger.info(
            "conversation_state_transitioned",
            conversation_instance_id=str(instance.pk),
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            source_event_id=source_event_id,
        )
        return instance

    def transition_by_ticket(self, ticket_id: str, to_state: str, *, reason: str, actor_id: str = "") -> bool:
        instance = ConversationInstance.objects.filter(hubspot_ticket_id=str(ticket_id)).first()
        if instance is None:
            return False
        self.transition(instance, to_state, reason=reason, actor_id=actor_id)
        return True

    def transition_by_thread(self, thread_id: str, to_state: str, *, reason: str, actor_id: str = "") -> bool:
        instance = ConversationInstance.objects.filter(hubspot_thread_id=str(thread_id)).first()
        if instance is None:
            return False
        self.transition(instance, to_state, reason=reason, actor_id=actor_id)
        return True

    def record_agent_run(
        self,
        *,
        instance: ConversationInstance | None,
        agent_name: str,
        input_snapshot: dict[str, Any],
        output_structured: dict[str, Any] | None = None,
        tokens_used: int = 0,
        latency_ms: int = 0,
        status: str = AgentRun.Status.SUCCEEDED,
        error_message: str = "",
    ) -> AgentRun:
        return AgentRun.objects.create(
            instance=instance,
            agent_name=agent_name,
            input_snapshot=input_snapshot,
            output_structured=output_structured or {},
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
        )

    def record_tool_call(
        self,
        *,
        instance: ConversationInstance,
        tool_name: str,
        idempotency_key: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any] | None = None,
        status: str = ToolCallAuditLog.Status.SUCCEEDED,
        agent_run: AgentRun | None = None,
        external_object_type: str = "",
        external_object_id: str = "",
    ) -> ToolCallAuditLog:
        log, _created = ToolCallAuditLog.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "instance": instance,
                "agent_run": agent_run,
                "tool_name": tool_name,
                "input": input_payload,
                "output": output_payload or {},
                "status": status,
                "external_object_type": external_object_type,
                "external_object_id": external_object_id,
            },
        )
        return log

    def _get_or_create_instance(self, event: NormalizedEvent) -> tuple[ConversationInstance, bool]:
        defaults = {
            "hubspot_thread_id": event.hubspot_thread_id,
            "hubspot_ticket_id": event.hubspot_ticket_id,
            "hubspot_contact_id": event.hubspot_contact_id,
            "channel": event.channel,
            "pipeline_id": event.pipeline_id,
            "pipeline_stage_id": event.pipeline_stage_id,
            "last_event_id": event.source_event_id,
            "last_message_id": event.message_id,
            "last_activity_at": event.occurred_at or timezone.now(),
            "ai_session_id": self._ai_session_id(event),
            "metadata": {"last_payload": event.payload},
        }

        lookup: dict[str, str] | None = None
        idempotency_key = self._instance_idempotency_key(event)
        if event.hubspot_thread_id:
            lookup = {"hubspot_thread_id": event.hubspot_thread_id}
        elif event.hubspot_ticket_id:
            lookup = {"hubspot_ticket_id": event.hubspot_ticket_id}

        if lookup:
            instance = ConversationInstance.objects.filter(**lookup).select_for_update().first()
            if instance:
                return instance, False

        try:
            return ConversationInstance.objects.create(idempotency_key=idempotency_key, **defaults), True
        except IntegrityError:
            instance = ConversationInstance.objects.select_for_update().get(idempotency_key=idempotency_key)
            return instance, False

    def _append_event(
        self,
        instance: ConversationInstance,
        event: NormalizedEvent,
    ) -> tuple[ConversationEvent, bool]:
        return ConversationEvent.objects.get_or_create(
            idempotency_key=event.idempotency_key,
            defaults={
                "instance": instance,
                "source": event.source,
                "source_event_id": event.source_event_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "payload": event.payload,
            },
        )

    def _refresh_instance_snapshot(self, instance: ConversationInstance, event: NormalizedEvent) -> None:
        update_fields = ["last_event_id", "last_message_id", "last_activity_at", "metadata", "updated_at"]
        instance.last_event_id = event.source_event_id or instance.last_event_id
        instance.last_message_id = event.message_id or instance.last_message_id
        instance.last_activity_at = event.occurred_at or timezone.now()
        if event.hubspot_contact_id:
            instance.hubspot_contact_id = event.hubspot_contact_id
            update_fields.append("hubspot_contact_id")
        if event.channel != "unknown":
            instance.channel = event.channel
            update_fields.append("channel")
        if event.pipeline_id:
            instance.pipeline_id = event.pipeline_id
            update_fields.append("pipeline_id")
        if event.pipeline_stage_id:
            instance.pipeline_stage_id = event.pipeline_stage_id
            update_fields.append("pipeline_stage_id")
        metadata = dict(instance.metadata or {})
        metadata["last_payload"] = event.payload
        instance.metadata = metadata
        instance.save(update_fields=list(dict.fromkeys(update_fields)))

    def _validate_transition(self, from_state: str, to_state: str, *, allow_terminal_reopen: bool = False) -> None:
        if from_state in TERMINAL_STATES and not allow_terminal_reopen:
            raise InvalidStateTransitionError(f"Cannot transition terminal state {from_state} to {to_state}.")
        if to_state in {ConversationInstance.State.CLOSED, ConversationInstance.State.RESOLVED_BY_HUMAN}:
            return
        if to_state == ConversationInstance.State.HUMAN_HANDOFF_REQUESTED and from_state in ACTIVE_STATES:
            return
        if to_state in {ConversationInstance.State.FAILED_RETRYABLE, ConversationInstance.State.IGNORED}:
            return
        if (
            to_state == ConversationInstance.State.FAILED_TERMINAL
            and from_state == ConversationInstance.State.FAILED_RETRYABLE
        ):
            return
        allowed = VALID_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            raise InvalidStateTransitionError(f"Invalid transition {from_state} -> {to_state}.")

    def _instance_idempotency_key(self, event: NormalizedEvent) -> str:
        if event.hubspot_thread_id:
            return f"conversation:thread:{event.hubspot_thread_id}"
        if event.hubspot_ticket_id:
            return f"conversation:ticket:{event.hubspot_ticket_id}"
        return f"conversation:event:{event.idempotency_key}"

    def _ai_session_id(self, event: NormalizedEvent) -> str:
        if event.hubspot_ticket_id:
            return f"hubspot-ticket-{event.hubspot_ticket_id}"
        if event.hubspot_thread_id:
            return f"hubspot-thread-{event.hubspot_thread_id}"
        return f"event-{event.source_event_id or event.idempotency_key}"


def record_lifecycle_for_webhook_event(event: Any) -> LifecycleRecordResult:
    """Normalize, route, and record a WebhookEvent in the lifecycle ledger."""
    normalized = EventNormalizer().normalize_webhook_event(event)
    decision = RoutingPolicyEngine().route(normalized)
    return LifecycleEngine().record_normalized_event(normalized, decision=decision)


__all__ = [
    "EventNormalizer",
    "InvalidStateTransitionError",
    "LifecycleEngine",
    "LifecycleRecordResult",
    "NormalizedEvent",
    "RouteDecision",
    "RoutingPolicyEngine",
    "is_lifecycle_schema_ready",
    "record_lifecycle_for_webhook_event",
]
