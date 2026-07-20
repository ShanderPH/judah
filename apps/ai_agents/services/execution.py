"""Audited application of structured Supervisor decisions."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.utils import timezone

from apps.ai_agents.agents.base import DEFAULT_MINI_MODEL_ID
from apps.ai_agents.agents.supervisor import SalomaoResponse
from apps.ai_agents.contracts import ConversationContext, SupervisorDecision, TriageDecision
from apps.ai_agents.models import AgentRun, ConversationInstance, ToolCallAuditLog
from apps.ai_agents.services.handoff import build_handoff_package
from apps.ai_agents.services.lifecycle import LifecycleEngine
from apps.ai_agents.services.tool_permissions import is_tool_allowed

logger = structlog.get_logger(__name__)

HUMAN_HANDOFF_CONFIRMATION = (
    "Entendi. Vou encaminhar seu atendimento para uma pessoa do nosso time agora. "
    "Ela continuará a conversa por aqui com o contexto que você já enviou."
)


def _text_fingerprint(text: str) -> dict[str, Any]:
    """Return an auditable fingerprint without duplicating customer PII."""
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "length": len(text),
    }


@dataclass(frozen=True)
class PreparedToolCall:
    """Result of preparing an idempotent tool execution."""

    audit_id: str
    should_execute: bool
    cached_output: dict[str, Any]


def ensure_conversation_instance(
    *,
    context: dict[str, Any],
    ticket_id: str | None,
    session_id: str,
) -> ConversationInstance:
    """Return the canonical lifecycle instance, creating a safe fallback if needed."""
    thread_ids = context.get("thread_ids") or []
    if thread_ids:
        instance = ConversationInstance.objects.filter(hubspot_thread_id=str(thread_ids[0])).first()
        if instance is not None:
            return instance
    effective_ticket_id = str(ticket_id or context.get("ticket_id") or "") or None
    if effective_ticket_id:
        instance = ConversationInstance.objects.filter(hubspot_ticket_id=effective_ticket_id).first()
        if instance is not None:
            return instance

    thread_id = str(thread_ids[0]) if thread_ids else None
    idempotency_key = (
        f"conversation:thread:{thread_id}"
        if thread_id
        else f"conversation:ticket:{effective_ticket_id}"
        if effective_ticket_id
        else f"conversation:session:{session_id}"
    )
    return ConversationInstance.objects.create(
        idempotency_key=idempotency_key,
        hubspot_thread_id=thread_id,
        hubspot_ticket_id=effective_ticket_id,
        channel=str(context.get("originating_channel") or "unknown"),
        pipeline_id=str(context.get("pipeline") or "") or None,
        pipeline_stage_id=str(context.get("pipeline_stage") or "") or None,
        state=ConversationInstance.State.CONTEXT_HYDRATING,
        ai_session_id=session_id,
        last_activity_at=timezone.now(),
        metadata={"created_by": "supervisor_worker_fallback"},
    )


def _prepare_tool_call(
    *,
    instance: ConversationInstance,
    tool_name: str,
    idempotency_key: str,
    input_payload: dict[str, Any],
    agent_run: AgentRun | None,
) -> PreparedToolCall:
    audit = ToolCallAuditLog.objects.filter(idempotency_key=idempotency_key).first()
    if audit is not None and audit.status == ToolCallAuditLog.Status.SUCCEEDED:
        return PreparedToolCall(
            audit_id=str(audit.pk),
            should_execute=False,
            cached_output=dict(audit.output or {}),
        )

    if not is_tool_allowed(instance.state, tool_name):
        raise PermissionError(f"Tool {tool_name} is not allowed in state {instance.state}.")

    if audit is None:
        audit = ToolCallAuditLog.objects.create(
            instance=instance,
            agent_run=agent_run,
            tool_name=tool_name,
            input=input_payload,
            status=ToolCallAuditLog.Status.STARTED,
            idempotency_key=idempotency_key,
        )
    else:
        audit.instance = instance
        audit.agent_run = agent_run
        audit.tool_name = tool_name
        audit.input = input_payload
        audit.output = {}
        audit.status = ToolCallAuditLog.Status.STARTED
        audit.error_message = ""
        audit.save(
            update_fields=[
                "instance",
                "agent_run",
                "tool_name",
                "input",
                "output",
                "status",
                "error_message",
            ]
        )

    return PreparedToolCall(audit_id=str(audit.pk), should_execute=True, cached_output={})


def _finish_tool_call(
    audit_id: str,
    *,
    output: dict[str, Any],
    succeeded: bool,
    error_message: str = "",
) -> None:
    audit = ToolCallAuditLog.objects.get(pk=audit_id)
    audit.output = output
    audit.status = ToolCallAuditLog.Status.SUCCEEDED if succeeded else ToolCallAuditLog.Status.FAILED
    audit.error_message = error_message
    audit.save(update_fields=["output", "status", "error_message"])


def record_supervisor_runs(
    *,
    instance: ConversationInstance,
    message: str,
    result: SalomaoResponse,
) -> AgentRun:
    """Persist correlated Heimdall and Supervisor execution snapshots."""
    engine = LifecycleEngine()
    triage = result.triage_decision
    if triage is not None:
        engine.record_agent_run(
            instance=instance,
            agent_name="Heimdall",
            model_name=DEFAULT_MINI_MODEL_ID,
            prompt_version="heimdall-v1",
            policy_version=triage.policy_version,
            input_snapshot={"message": _text_fingerprint(message)},
            output_structured=triage.model_dump(mode="json"),
            status=AgentRun.Status.SUCCEEDED,
        )

    decision = result.decision or SupervisorDecision(
        outcome="escalate_human" if result.requires_human_handoff else "waiting_customer",
        final_response=result.message,
        trace_summary=result.agent_trace,
        risk_flags=["legacy_supervisor_response"],
        confidence=0.5,
    )
    return engine.record_agent_run(
        instance=instance,
        agent_name="SalomaoSupervisor",
        model_name=result.model_name,
        prompt_version="salomao-supervisor-v1",
        policy_version=triage.policy_version if triage else "supervisor-v1",
        input_snapshot={"message": _text_fingerprint(message)},
        output_structured=decision.model_dump(mode="json"),
        tokens_used=result.tokens_used,
        latency_ms=result.latency_ms,
        status=AgentRun.Status.SUCCEEDED,
    )


async def send_reply_with_audit(
    *,
    instance: ConversationInstance,
    context: dict[str, Any],
    text: str,
    agent_run: AgentRun | None,
    idempotency_key: str,
) -> dict[str, Any]:
    """Send a HubSpot thread reply with permission and idempotency enforcement."""
    from apps.ai_agents.services.hubspot import send_salomao_reply_to_hubspot_thread

    prepared = await sync_to_async(_prepare_tool_call)(
        instance=instance,
        tool_name="send_thread_reply",
        idempotency_key=idempotency_key,
        input_payload={
            "reply": _text_fingerprint(text),
            "thread_ids": context.get("thread_ids") or [],
        },
        agent_run=agent_run,
    )
    if not prepared.should_execute:
        return prepared.cached_output

    try:
        output = await send_salomao_reply_to_hubspot_thread(context, text)
    except Exception as exc:
        await sync_to_async(_finish_tool_call)(
            prepared.audit_id,
            output={},
            succeeded=False,
            error_message=str(exc),
        )
        raise

    await sync_to_async(_finish_tool_call)(
        prepared.audit_id,
        output=output,
        succeeded=bool(output.get("sent")),
        error_message="" if output.get("sent") else str(output.get("reason") or "reply_failed"),
    )
    return output


def request_human_handoff(
    *,
    instance: ConversationInstance,
    reason: str,
    conversation_context: ConversationContext | None,
    triage_decision: TriageDecision | None,
    ai_summary: str,
    agent_run: AgentRun | None = None,
) -> dict[str, Any]:
    """Move the ticket to human support and persist it in Matchmaker.

    Return only after HubSpot accepted the human-support route and the local
    queue row exists, so callers never promise a transfer before it happened.
    """
    engine = LifecycleEngine()
    if instance.state != ConversationInstance.State.HUMAN_HANDOFF_REQUESTED:
        engine.transition(
            instance,
            ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
            reason=reason,
            actor_type="supervisor",
        )

    package = build_handoff_package(
        instance=instance,
        reason=reason,
        conversation_context=conversation_context,
        triage_decision=triage_decision,
        ai_summary=ai_summary,
    )
    engine.update_metadata(
        instance,
        handoff_package=package,
        awaiting_resolution_confirmation=False,
        waiting_for_fields=[],
    )

    if (
        conversation_context is not None
        and conversation_context.allowed_actions
        and "assign_ticket_to_human_queue" not in conversation_context.allowed_actions
    ):
        logger.warning(
            "human_handoff_tool_not_allowed",
            conversation_instance_id=str(instance.pk),
            allowed_actions=conversation_context.allowed_actions,
        )
        raise PermissionError("Human handoff is not allowed for this conversation context.")

    ticket_id = instance.hubspot_ticket_id or (
        conversation_context.ticket_id if conversation_context is not None else None
    )
    if not ticket_id:
        raise ValueError("Human handoff requires a HubSpot ticket ID.")

    idempotency_key = f"handoff:v2:{instance.pk}:{ticket_id}"
    prepared = _prepare_tool_call(
        instance=instance,
        tool_name="assign_ticket_to_human_queue",
        idempotency_key=idempotency_key,
        input_payload={
            "ticket_id": str(ticket_id),
            "priority": package.get("priority") or "",
            "reason": _text_fingerprint(reason),
            "summary": _text_fingerprint(ai_summary),
        },
        agent_run=agent_run,
    )
    output = prepared.cached_output
    if prepared.should_execute:
        try:
            from apps.ai_agents.services.hubspot import update_hubspot_ticket_route
            from apps.support.matchmaker_service import enqueue_handoff_ticket
            from apps.support.tasks import task_matchmaker_drain_queue

            support_pipeline_id = str(settings.HUBSPOT_SUPPORT_PIPELINE_ID)
            support_stage_id = str(settings.HUBSPOT_SUPPORT_NEW_STAGE_ID)
            route_result = async_to_sync(update_hubspot_ticket_route)(
                str(ticket_id),
                support_stage_id,
                pipeline_id=support_pipeline_id,
            )
            if not route_result.get("updated"):
                raise RuntimeError(
                    f"HubSpot rejected the human-support route: {route_result.get('reason') or 'unknown error'}"
                )

            queue_row = enqueue_handoff_ticket(
                str(ticket_id),
                pipeline_id=support_pipeline_id,
                priority=package.get("priority") or "",
                subject=ai_summary[:255],
            )
            output = {
                "queued": True,
                "queue_id": str(queue_row.pk),
                "ticket_id": str(ticket_id),
                "pipeline_id": support_pipeline_id,
                "stage_id": support_stage_id,
                "route_updated": True,
            }
            _finish_tool_call(prepared.audit_id, output=output, succeeded=True)
            try:
                task_matchmaker_drain_queue.delay()
            except Exception as exc:
                # The durable queue row and HubSpot human route already exist;
                # Beat will retry the drain if Redis dispatch is degraded.
                logger.warning(
                    "human_handoff_matchmaker_dispatch_deferred",
                    ticket_id=str(ticket_id),
                    error=str(exc),
                )
        except Exception as exc:
            _finish_tool_call(
                prepared.audit_id,
                output={},
                succeeded=False,
                error_message=str(exc),
            )
            raise

    if not output.get("queued") or not output.get("route_updated"):
        raise RuntimeError("Human handoff did not complete its durable routing effects.")

    engine.update_metadata(instance, human_handoff_dispatch=output)

    if instance.state != ConversationInstance.State.QUEUE_PENDING:
        engine.transition(
            instance,
            ConversationInstance.State.QUEUE_PENDING,
            reason="Human handoff package enqueued for Matchmaker.",
            actor_type="system",
        )
    return {**package, "dispatch": output}


def mark_retryable_failure(instance: ConversationInstance, error: Exception | str) -> None:
    """Persist bounded failure state for a later retry task."""
    instance.failure_count += 1
    instance.current_error = str(error)
    instance.next_retry_at = timezone.now() + timedelta(minutes=5)
    instance.save(update_fields=["failure_count", "current_error", "next_retry_at", "updated_at"])
    if instance.state != ConversationInstance.State.FAILED_RETRYABLE:
        LifecycleEngine().transition(
            instance,
            ConversationInstance.State.FAILED_RETRYABLE,
            reason=f"Retryable AI workflow failure: {error}",
        )


def _set_waiting_state(
    instance: ConversationInstance,
    *,
    decision: SupervisorDecision,
) -> None:
    """Persist the waiting state and deterministic resume metadata."""
    engine = LifecycleEngine()
    engine.transition(
        instance,
        ConversationInstance.State.WAITING_FOR_CUSTOMER,
        reason="Response sent; waiting for additional customer input.",
        actor_type="supervisor",
    )
    engine.update_metadata(
        instance,
        awaiting_resolution_confirmation=False,
        waiting_for_fields=decision.missing_data,
        last_supervisor_decision=decision.model_dump(mode="json"),
    )


async def apply_supervisor_result(
    *,
    instance: ConversationInstance,
    context: dict[str, Any],
    conversation_context: ConversationContext,
    message: str,
    result: SalomaoResponse,
) -> None:
    """Apply a structured decision and its external effects."""
    decision = result.decision or SupervisorDecision(
        outcome="escalate_human" if result.requires_human_handoff else "waiting_customer",
        final_response=result.message,
        trace_summary=result.agent_trace,
        risk_flags=["legacy_supervisor_response"],
        confidence=0.5,
    )
    agent_run = await sync_to_async(record_supervisor_runs)(
        instance=instance,
        message=message,
        result=result,
    )

    if decision.outcome == "failed":
        await sync_to_async(mark_retryable_failure)(instance, "Supervisor returned failed outcome.")
        raise RuntimeError("Supervisor returned failed outcome.")

    can_reply = conversation_context.can_send_reply and bool(conversation_context.thread_id)
    reply_tool_allowed = (
        not conversation_context.allowed_actions or "send_thread_reply" in conversation_context.allowed_actions
    )

    if decision.outcome == "escalate_human":
        if can_reply and reply_tool_allowed:
            reply_result = await send_reply_with_audit(
                instance=instance,
                context=context,
                text=HUMAN_HANDOFF_CONFIRMATION,
                agent_run=agent_run,
                idempotency_key=(
                    f"handoff-confirmation:v2:{instance.pk}:{instance.last_message_id or instance.last_event_id}"
                ),
            )
            if not reply_result.get("sent"):
                raise RuntimeError(reply_result.get("reason") or "HubSpot handoff confirmation failed.")

        await sync_to_async(request_human_handoff)(
            instance=instance,
            reason=result.handoff_reason or "Supervisor requested human handoff.",
            conversation_context=conversation_context,
            triage_decision=result.triage_decision,
            ai_summary=decision.final_response,
            agent_run=agent_run,
        )
        return

    if can_reply and decision.final_response and not reply_tool_allowed:
        await sync_to_async(request_human_handoff)(
            instance=instance,
            reason="The normalized context does not authorize an automated reply.",
            conversation_context=conversation_context,
            triage_decision=result.triage_decision,
            ai_summary=decision.final_response,
            agent_run=agent_run,
        )
        return

    if can_reply and decision.final_response:
        reply_key = (
            f"{decision.hubspot_action.idempotency_key}:{instance.last_message_id or instance.last_event_id}"
            if decision.hubspot_action is not None
            else f"reply:{instance.pk}:{instance.last_message_id or instance.last_event_id}"
        )
        reply_result = await send_reply_with_audit(
            instance=instance,
            context=context,
            text=decision.final_response,
            agent_run=agent_run,
            idempotency_key=reply_key,
        )
        if not reply_result.get("sent"):
            await sync_to_async(mark_retryable_failure)(
                instance,
                reply_result.get("reason") or "HubSpot reply failed.",
            )
            raise RuntimeError(reply_result.get("reason") or "HubSpot reply failed.")

    await sync_to_async(_set_waiting_state)(instance, decision=decision)


def _normalized_confirmation(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.strip().lower())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", without_accents).split())


def handle_resolution_confirmation(instance: ConversationInstance, message: str) -> bool:
    """Close only when a prior candidate resolution receives clear confirmation."""
    metadata = dict(instance.metadata or {})
    if not metadata.get("awaiting_resolution_confirmation"):
        return False

    normalized = _normalized_confirmation(message)
    positive = {
        "sim",
        "sim resolveu",
        "resolveu",
        "resolvido",
        "funcionou",
        "deu certo",
        "obrigado resolveu",
        "obrigada resolveu",
    }
    if normalized in positive:
        engine = LifecycleEngine()
        engine.transition(
            instance,
            ConversationInstance.State.RESOLVED_BY_AI,
            reason="Customer confirmed the candidate resolution.",
            actor_type="customer",
        )
        engine.transition(
            instance,
            ConversationInstance.State.CLOSED,
            reason="AI resolution confirmed by customer.",
            actor_type="system",
        )
        engine.update_metadata(
            instance,
            awaiting_resolution_confirmation=False,
            waiting_for_fields=[],
        )
        return True

    metadata["awaiting_resolution_confirmation"] = False
    instance.metadata = metadata
    instance.save(update_fields=["metadata", "updated_at"])
    return False


__all__ = [
    "apply_supervisor_result",
    "ensure_conversation_instance",
    "handle_resolution_confirmation",
    "mark_retryable_failure",
    "record_supervisor_runs",
    "request_human_handoff",
    "send_reply_with_audit",
]
