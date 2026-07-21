"""Integrated audit checks for a HubSpot AI turn."""

import pytest
from asgiref.sync import sync_to_async

from apps.ai_agents.api.webhooks import _record_hubspot_turn_audit
from apps.ai_agents.contracts import ConversationContext, ConversationMessage, TriageDecision
from apps.ai_agents.models import AgentRun, ConversationInstance, ToolCallAuditLog


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_handoff_turn_records_agent_tools_and_package() -> None:
    instance = await sync_to_async(ConversationInstance.objects.create)(
        idempotency_key="conversation:thread:thread-audit-1",
        hubspot_ticket_id="audit-1",
        hubspot_thread_id="thread-audit-1",
        state=ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
        channel="whatsapp",
    )
    conversation_context = ConversationContext(
        channel="hubspot",
        session_id="hubspot-thread-thread-audit-1",
        ticket_id="audit-1",
        thread_id="thread-audit-1",
        recent_messages=[
            ConversationMessage(direction="INCOMING", text="Nada funciona", message_id="message-1"),
        ],
    )
    triage = TriageDecision(
        rota="ESCALAR_IMEDIATAMENTE",
        prioridade="ALTA",
        sentimento="negativo",
        confidence=0.98,
        evidence=["cliente relata falha total"],
    )

    await _record_hubspot_turn_audit(
        context={
            "ticket_id": "audit-1",
            "thread_ids": ["thread-audit-1"],
            "conversation_history": [
                {"id": "message-1", "direction": "INCOMING", "text": "Nada funciona"},
            ],
        },
        ticket_id="audit-1",
        session_id="hubspot-thread-thread-audit-1",
        agent_name="SalomaoSupervisorAgent",
        output_structured={
            "message": "Vou encaminhar ao time humano.",
            "outcome": "escalate_human",
            "missing_data": [],
            "triage_decision": triage.model_dump(mode="json"),
            "agent_trace": ["heimdall: OK", "salomao_chat: OK"],
            "confidence": 0.98,
            "model_name": "salomao-v1",
        },
        reply_result={"sent": True, "message_id": "out-1"},
        active_stage_result={"updated": True, "stage_id": "active"},
        final_stage_result={"updated": True, "stage_id": "human"},
        conversation_context=conversation_context,
        triage_decision=triage,
        handoff_reason="High-impact frustrated customer.",
        tokens_used=42,
        latency_ms=1200,
    )

    assert await sync_to_async(AgentRun.objects.filter(instance=instance).count)() == 3
    assert await sync_to_async(ToolCallAuditLog.objects.filter(instance=instance).count)() == 3
    reply_audit = await sync_to_async(ToolCallAuditLog.objects.get)(
        instance=instance,
        tool_name="send_thread_reply",
    )
    assert reply_audit.external_object_type == "hubspot_thread"
    assert reply_audit.external_object_id == "thread-audit-1"
    stage_audits = ToolCallAuditLog.objects.filter(instance=instance, tool_name__contains="stage")
    assert await sync_to_async(stage_audits.filter(external_object_id="audit-1").count)() == 2
    await sync_to_async(instance.refresh_from_db)()
    package = instance.metadata["handoff_package"]
    assert package["reason"] == "High-impact frustrated customer."
    assert package["priority"] == "ALTA"
    assert package["recent_messages"][0]["message_id"] == "message-1"
