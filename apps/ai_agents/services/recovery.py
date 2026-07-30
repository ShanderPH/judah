"""Auditable, single-ticket operational recovery for suppressed customer turns."""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from apps.ai_agents.models import AgentRun, ConversationInstance, ToolCallAuditLog
from apps.ai_agents.services.conversation_turn import current_incoming_turn_audit
from apps.ai_agents.services.hubspot import (
    evaluate_salomao_ticket_eligibility,
    hydrate_ticket_context,
)
from apps.ai_agents.services.instance_identity import find_conversation_instance


async def inspect_ticket_recovery(ticket_id: str) -> dict[str, Any]:
    """Rehydrate one ticket and return a PII-minimal recovery decision."""
    normalized_ticket_id = str(ticket_id).strip()
    context = await hydrate_ticket_context(normalized_ticket_id)
    thread_ids = [str(value) for value in context.get("thread_ids") or [] if value]
    thread_id = thread_ids[0] if len(thread_ids) == 1 else ""
    eligibility = evaluate_salomao_ticket_eligibility(context)
    turn = current_incoming_turn_audit(context)
    instance = (
        await sync_to_async(find_conversation_instance)(
            thread_id=thread_id or None,
            ticket_id=normalized_ticket_id,
        )
        if thread_id
        else None
    )
    reasons: list[str] = []
    if len(thread_ids) != 1:
        reasons.append("canonical_thread_not_resolved")
    if instance is None:
        reasons.append("canonical_instance_not_found")
    if not eligibility["eligible"]:
        reasons.append(str(eligibility["reason"]))
    if turn is None:
        reasons.append("no_current_customer_turn")

    return {
        "ticket_id": normalized_ticket_id,
        "thread_id": thread_id or None,
        "instance_id": str(instance.pk) if instance is not None else None,
        "customer_turn": turn,
        "pipeline": context.get("pipeline") or None,
        "pipeline_stage": context.get("pipeline_stage") or None,
        "owner_present": bool(str(context.get("owner_id") or "").strip()),
        "eligible": not reasons,
        "reasons": reasons,
        "provider_errors": list(context.get("errors") or []),
    }


def execute_ticket_recovery(*, inspection: dict[str, Any], operator: str) -> dict[str, Any]:
    """Audit and enqueue one verified recovery; duplicate execution is a no-op."""
    if not inspection.get("eligible"):
        raise ValueError(f"Ticket is not safe to recover: {', '.join(inspection.get('reasons') or [])}")
    instance = ConversationInstance.objects.get(pk=inspection["instance_id"])
    thread_id = str(inspection["thread_id"])
    turn = dict(inspection["customer_turn"])
    message_id = str(turn["last_message_id"])
    key = f"operational-recovery:v1:{inspection['ticket_id']}:{thread_id}:{message_id}"

    with transaction.atomic():
        existing = ToolCallAuditLog.objects.select_for_update().filter(idempotency_key=key).first()
        if existing is not None and existing.status == ToolCallAuditLog.Status.SUCCEEDED:
            return {"scheduled": False, "deduplicated": True, "audit_id": str(existing.pk)}

        agent_run = AgentRun.objects.create(
            instance=instance,
            agent_name="OperationalRecovery",
            model_name="deterministic",
            prompt_version="single-ticket-recovery-v1",
            policy_version="production-failures-f07",
            input_snapshot={
                "ticket_id": inspection["ticket_id"],
                "thread_id": thread_id,
                "customer_turn_id": message_id,
                "operator": operator,
            },
            output_structured={
                "route_revalidated": True,
                "owner_present": inspection["owner_present"],
                "provider_errors": inspection["provider_errors"],
                "scheduled_at": timezone.now().isoformat(),
            },
            status=AgentRun.Status.STARTED,
        )
        if existing is None:
            audit = ToolCallAuditLog.objects.create(
                instance=instance,
                agent_run=agent_run,
                tool_name="schedule_operational_recovery",
                input={"ticket_id": inspection["ticket_id"], "thread_id": thread_id, "operator": operator},
                status=ToolCallAuditLog.Status.STARTED,
                idempotency_key=key,
            )
        else:
            audit = existing
            audit.agent_run = agent_run
            audit.status = ToolCallAuditLog.Status.STARTED
            audit.error_message = ""
            audit.save(update_fields=["agent_run", "status", "error_message"])

    try:
        from apps.ai_agents.tasks import run_salomao_v1_thread_pipeline_task

        run_salomao_v1_thread_pipeline_task.delay(thread_id)
    except Exception as exc:
        audit.status = ToolCallAuditLog.Status.FAILED
        audit.error_message = str(exc)
        audit.output = {"scheduled": False, "error_type": type(exc).__name__}
        audit.save(update_fields=["status", "error_message", "output"])
        agent_run.status = AgentRun.Status.FAILED
        agent_run.error_message = str(exc)
        agent_run.save(update_fields=["status", "error_message"])
        raise

    audit.status = ToolCallAuditLog.Status.SUCCEEDED
    audit.output = {"scheduled": True, "thread_id": thread_id, "customer_turn_id": message_id}
    audit.save(update_fields=["status", "output"])
    agent_run.status = AgentRun.Status.SUCCEEDED
    agent_run.save(update_fields=["status"])
    return {"scheduled": True, "deduplicated": False, "audit_id": str(audit.pk)}


__all__ = ["execute_ticket_recovery", "inspect_ticket_recovery"]
