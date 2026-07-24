"""Webhook inbound do HubSpot → dispara o SalomaoSupervisorAgent.

Este router é a porta de entrada do ecossistema multi-agente. A responsabilidade
é estreita:
    1. Validar a assinatura do HubSpot (v1 ou v3).
    2. Extrair `ticket_id` do payload.
    3. Aplicar as regras de negócio (horário comercial, Quinta Fire, feriados).
    4. Despachar o trabalho pesado para o Celery (`.delay(...)`) e retornar
       HTTP 202 imediatamente — o HubSpot desiste do webhook se a resposta
       passar de ~5s, então NUNCA aguardamos o LLM neste request.

A task do Celery aplica uma trava de idempotência em Redis (SETNX) para
não reprocessar o mesmo ticket quando o HubSpot faz retry do webhook.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from ninja import Router, Schema

from apps.ai_agents.agents.supervisor import SalomaoResponse, SalomaoSupervisorAgent
from apps.ai_agents.contracts import SupervisorDecision
from apps.ai_agents.models import AgentRun, ConversationInstance, TokenTrackingLog, ToolCallAuditLog
from apps.ai_agents.services.commercial_contact import handle_commercial_contact_from_hubspot_context
from apps.ai_agents.services.content_safety import assess_customer_content
from apps.ai_agents.services.execution import (
    apply_supervisor_result,
    ensure_conversation_instance,
    handle_resolution_confirmation,
    mark_retryable_failure,
    request_human_handoff,
)
from apps.ai_agents.services.handoff import build_handoff_package
from apps.ai_agents.services.hubspot import (
    USE_MOCK_HUBSPOT,
    build_conversation_context_from_hubspot_context,
    build_salomao_prompt_from_hubspot_context,
    hydrate_thread_context,
    hydrate_ticket_context,
)
from apps.ai_agents.services.instance_identity import find_conversation_instance
from apps.ai_agents.services.lifecycle import (
    InvalidStateTransitionError,
    LifecycleEngine,
    is_lifecycle_schema_ready,
)
from apps.ai_agents.services.protocol_lookup import handle_protocol_lookup_from_hubspot_context
from apps.ai_agents.tasks import run_supervisor_pipeline_task
from apps.ai_agents.utils.business_rules import (
    is_business_hours,
    is_quinta_fire,
    off_hours_reason,
)
from apps.ai_agents.utils.pricing import calculate_cost
from apps.webhooks.signatures import (
    is_valid_hubspot_request,
    verify_hubspot_signature_v1,
    verify_hubspot_signature_v3,
)

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = structlog.get_logger(__name__)

router = Router()


def _deterministic_response(*, session_id: str, message: str, policy: str) -> SalomaoResponse:
    """Build a zero-token response produced by a deterministic policy."""
    final_response = message.rstrip()
    trace = [f"{policy}: OK", "supervisor: candidate_resolved"]
    return SalomaoResponse(
        session_id=session_id,
        message=final_response,
        sources=[],
        requires_human_handoff=False,
        handoff_reason=None,
        agent_trace=trace,
        tokens_used=0,
        model_name=policy,
        latency_ms=0,
        decision=SupervisorDecision(
            outcome="candidate_resolved",
            final_response=final_response,
            trace_summary=trace,
            confidence=1.0,
        ),
    )


def _hubspot_turn_source(context: dict[str, Any], *, session_id: str) -> str:
    """Build a stable source ID even when HubSpot omits a message ID."""
    history = context.get("conversation_history") or []
    latest_incoming = next(
        (item for item in reversed(history) if str(item.get("direction") or "").upper() == "INCOMING"),
        None,
    )
    if not latest_incoming:
        return session_id
    if latest_incoming.get("id"):
        return str(latest_incoming["id"])
    fingerprint = {
        "created_at": latest_incoming.get("created_at"),
        "sender": latest_incoming.get("sender"),
        "text": latest_incoming.get("text"),
        "attachments": latest_incoming.get("attachments") or [],
    }
    return hashlib.sha256(json.dumps(fingerprint, sort_keys=True, default=str).encode("utf-8")).hexdigest()


@sync_to_async
def _record_hubspot_turn_audit(
    *,
    context: dict[str, Any],
    ticket_id: str | None,
    session_id: str,
    agent_name: str,
    output_structured: dict[str, Any],
    reply_result: dict[str, Any],
    active_stage_result: dict[str, Any],
    final_stage_result: dict[str, Any],
    conversation_context: Any | None = None,
    triage_decision: Any | None = None,
    handoff_reason: str | None = None,
    tokens_used: int = 0,
    latency_ms: int = 0,
) -> None:
    """Persist the legacy staging audit shape for compatibility."""
    if not is_lifecycle_schema_ready():
        logger.warning("hubspot_turn_audit_schema_missing", ticket_id=ticket_id, session_id=session_id)
        return
    thread_ids = context.get("thread_ids") or []
    instance = find_conversation_instance(
        thread_id=str(thread_ids[0]) if thread_ids else None,
        ticket_id=ticket_id,
    )
    if instance is None:
        return

    history = context.get("conversation_history") or []
    latest_incoming = next(
        (item for item in reversed(history) if str(item.get("direction") or "").upper() == "INCOMING"),
        {},
    )
    turn_key = hashlib.sha256(_hubspot_turn_source(context, session_id=session_id).encode("utf-8")).hexdigest()[:20]
    engine = LifecycleEngine()
    agent_run = engine.record_agent_run(
        instance=instance,
        agent_name=agent_name,
        input_snapshot={
            "session_id": session_id,
            "ticket_id": ticket_id,
            "thread_id": str(thread_ids[0]) if thread_ids else None,
            "message_id": latest_incoming.get("id"),
            "policy_version": (output_structured.get("triage_decision") or {}).get("policy_version"),
        },
        output_structured=output_structured,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        status=AgentRun.Status.SUCCEEDED,
    )

    triage_payload = output_structured.get("triage_decision")
    if isinstance(triage_payload, dict):
        engine.record_agent_run(
            instance=instance,
            agent_name="HeimdallTriageAgent",
            input_snapshot={"session_id": session_id, "message_id": latest_incoming.get("id")},
            output_structured=triage_payload,
            status=AgentRun.Status.SUCCEEDED,
        )
    trace = output_structured.get("agent_trace") or []
    if any("salomao_chat: OK" in str(item) for item in trace):
        engine.record_agent_run(
            instance=instance,
            agent_name="SalomaoChatAgent",
            input_snapshot={"session_id": session_id, "message_id": latest_incoming.get("id")},
            output_structured={
                "message": output_structured.get("message"),
                "confidence": output_structured.get("confidence"),
                "model_name": output_structured.get("model_name"),
            },
            status=AgentRun.Status.SUCCEEDED,
        )

    thread_id = str(thread_ids[0]) if thread_ids else ""
    effective_ticket_id = str(ticket_id or context.get("ticket_id") or "")
    effects = (
        ("update_ticket_stage_active", active_stage_result, "updated", "hubspot_ticket", effective_ticket_id),
        ("send_thread_reply", reply_result, "sent", "hubspot_thread", thread_id),
        ("update_ticket_stage_final", final_stage_result, "updated", "hubspot_ticket", effective_ticket_id),
    )
    for tool_name, effect_result, success_field, external_object_type, external_object_id in effects:
        succeeded = bool(effect_result.get(success_field))
        engine.record_tool_call(
            instance=instance,
            agent_run=agent_run,
            tool_name=tool_name,
            idempotency_key=f"{instance.pk}:{turn_key}:{tool_name}",
            input_payload={"ticket_id": ticket_id, "session_id": session_id},
            output_payload=effect_result,
            status=ToolCallAuditLog.Status.SUCCEEDED if succeeded else ToolCallAuditLog.Status.FAILED,
            external_object_type=external_object_type,
            external_object_id=external_object_id,
        )

    if handoff_reason:
        package = build_handoff_package(
            instance=instance,
            reason=handoff_reason,
            conversation_context=conversation_context,
            triage_decision=triage_decision,
            ai_summary=str(output_structured.get("message") or "")[:1000],
            missing_data=output_structured.get("missing_data") or [],
        )
        metadata = dict(instance.metadata or {})
        metadata["handoff_package"] = package
        instance.metadata = metadata
        instance.save(update_fields=["metadata", "updated_at"])


# ---------------------------------------------------------------------------
# Schemas Ninja
# ---------------------------------------------------------------------------


class WebhookAcceptedResponse(Schema):
    """Resposta mínima para o HubSpot. Corpo não é consumido por eles."""

    status: str
    ticket_id: str | None = None
    routed_to: str


class WebhookRejectedResponse(Schema):
    """Resposta para requests rejeitados por assinatura/payload inválidos."""

    detail: str
    error_code: str


# ---------------------------------------------------------------------------
# Verificação de assinatura HubSpot (v1 + v3)
# ---------------------------------------------------------------------------


def _verify_signature_v1(request: HttpRequest, secret: str) -> bool:
    """HubSpot v1: SHA-256(client_secret + request_body)."""
    return verify_hubspot_signature_v1(request, secret)


def _verify_signature_v3(request: HttpRequest, secret: str) -> bool:
    """HubSpot v3: HMAC-SHA256(method + uri + body + timestamp), Base64."""
    return verify_hubspot_signature_v3(request, secret)


def _signature_ok(request: HttpRequest) -> bool:
    """True se a assinatura v1 OU v3 casar. Em DEBUG sem secret, libera."""
    if USE_MOCK_HUBSPOT:
        # Modo simulador local: pula validação HMAC para permitir que o
        # script scripts/simulate_hubspot_webhook.py bata no endpoint sem
        # ter que replicar a assinatura v3 do HubSpot.
        return True
    secret: str = getattr(settings, "HUBSPOT_APP_SECRET", "") or ""
    if not secret:
        # Sem secret configurado: só permitimos em DEBUG para facilitar dev.
        return bool(getattr(settings, "DEBUG", False))
    return is_valid_hubspot_request(request, secret)


# ---------------------------------------------------------------------------
# Extração do ticket_id do payload HubSpot
# ---------------------------------------------------------------------------


def _extract_ticket_id(payload: list[dict[str, Any]] | dict[str, Any]) -> str | None:
    """HubSpot envia um array de eventos; pegamos o primeiro `objectId` válido."""
    events = payload if isinstance(payload, list) else [payload]
    for event in events:
        object_id = event.get("objectId")
        if object_id is not None:
            return str(object_id)
    return None


# ---------------------------------------------------------------------------
# Tasks em background
# ---------------------------------------------------------------------------


@sync_to_async
def _persist_token_tracking(
    *,
    session_id: str,
    ticket_id: str | None,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    """Grava um registro de TokenTrackingLog.

    Executa em thread pool via `sync_to_async` porque o ORM do Django ainda
    é síncrono. Falhas aqui não devem derrubar o pipeline — o chamador
    captura e loga.
    """
    TokenTrackingLog.objects.create(
        session_id=session_id,
        ticket_id=ticket_id,
        model_name=model_name or "unknown",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_cost_usd=Decimal(str(cost_usd)),
    )


async def _record_usage(ticket_id: str, session_id: str, result: SalomaoResponse) -> None:
    """Calcula custo e persiste o tracking; engole exceções de FinOps.

    O tracking é 'best-effort' — se o banco estiver fora, a resposta ao
    usuário não pode ser prejudicada. Por isso isolamos em try/except com
    log estruturado.
    """
    try:
        cost_usd = calculate_cost(
            result.model_name,
            result.prompt_tokens,
            result.completion_tokens,
        )
        await _persist_token_tracking(
            session_id=session_id,
            ticket_id=ticket_id,
            model_name=result.model_name,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=cost_usd,
        )
        logger.info(
            "token_tracking_recorded",
            ticket_id=ticket_id,
            session_id=session_id,
            model_name=result.model_name,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_cost_usd=cost_usd,
        )
    except Exception as exc:
        logger.error(
            "token_tracking_failed",
            ticket_id=ticket_id,
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


@sync_to_async
def _advance_lifecycle_for_hubspot_context(
    context: dict[str, Any],
    ticket_id: str | None,
    states: list[str],
    *,
    reason: str,
) -> None:
    """Best-effort lifecycle transition for async HubSpot worker paths."""
    thread_ids = context.get("thread_ids") or []
    instance = find_conversation_instance(
        thread_id=str(thread_ids[0]) if thread_ids else None,
        ticket_id=ticket_id or context.get("ticket_id"),
    )
    if instance is None:
        return

    engine = LifecycleEngine()
    for state in states:
        try:
            engine.transition(instance, state, reason=reason)
        except InvalidStateTransitionError as exc:
            logger.info(
                "lifecycle_transition_skipped",
                conversation_instance_id=str(instance.pk),
                current_state=instance.state,
                target_state=state,
                reason=str(exc),
            )
            break


def _build_hubspot_supervisor_message(context: dict[str, Any], ticket_id: str | None) -> str | None:
    prompt = build_salomao_prompt_from_hubspot_context(context)
    if prompt:
        return prompt

    history_lines = [
        f"[{m.get('direction')}] {m.get('text')}" for m in context.get("conversation_history", []) if m.get("text")
    ]
    history_block = "\n".join(history_lines) or context.get("content", "")
    if not history_block and not context.get("subject"):
        return None

    return (
        f"Ticket HubSpot #{ticket_id or context.get('ticket_id') or 'desconhecido'}\n"
        f"Assunto: {context.get('subject', '(sem assunto)')}\n"
        f"Canal: {context.get('originating_channel', 'desconhecido')}\n\n"
        f"Conteudo / Historico:\n{history_block}"
    )


def _latest_incoming_customer_text(context: dict[str, Any]) -> str:
    """Return only the latest raw customer text for deterministic policies."""
    for item in reversed(context.get("conversation_history") or []):
        if str(item.get("direction") or "").upper() == "INCOMING":
            return str(item.get("text") or "").strip()
    return ""


def _sanitize_latest_incoming_customer_text(context: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return a copied context with untrusted customer text normalized."""
    safe_context = deepcopy(context)
    history = safe_context.get("conversation_history") or []
    for item in reversed(history):
        if str(item.get("direction") or "").upper() != "INCOMING":
            continue
        assessment = assess_customer_content(str(item.get("text") or ""))
        item["text"] = assessment.sanitized_text
        return safe_context, assessment.risk_flags
    return safe_context, ()


@sync_to_async
def _prepare_instance_for_supervisor(instance: ConversationInstance) -> None:
    """Refresh a retryable instance so the worker can restart hydration."""
    instance.refresh_from_db()
    if instance.state == ConversationInstance.State.FAILED_RETRYABLE:
        LifecycleEngine().transition(
            instance,
            ConversationInstance.State.CONTEXT_HYDRATING,
            reason="Retry worker restarted context hydration.",
            actor_type="retry_worker",
        )


@sync_to_async
def _waiting_turn_already_has_reply(instance: ConversationInstance) -> bool:
    """Avoid invoking agents again for a customer turn already answered."""
    instance.refresh_from_db()
    turn_id = instance.last_message_id or instance.last_event_id
    if instance.state != ConversationInstance.State.WAITING_FOR_CUSTOMER or not turn_id:
        return False
    return ToolCallAuditLog.objects.filter(
        instance=instance,
        tool_name="send_thread_reply",
        idempotency_key=f"reply:{instance.pk}:{turn_id}",
        status=ToolCallAuditLog.Status.SUCCEEDED,
    ).exists()


@sync_to_async
def _resume_waiting_instance_for_customer_message(instance: ConversationInstance) -> None:
    """Start a new AI turn when a customer replies to a waiting conversation."""
    instance.refresh_from_db()
    if instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER:
        LifecycleEngine().transition(
            instance,
            ConversationInstance.State.CONTEXT_HYDRATING,
            reason="New customer message resumed context hydration.",
            actor_type="supervisor_worker",
        )


@sync_to_async
def _mark_pipeline_failure(
    *,
    ticket_id: str | None = None,
    thread_id: str | None = None,
    error: Exception,
) -> None:
    """Correlate uncaught worker failures with the lifecycle retry budget."""
    instance = find_conversation_instance(thread_id=thread_id, ticket_id=ticket_id)
    if instance is not None and instance.state != ConversationInstance.State.FAILED_RETRYABLE:
        mark_retryable_failure(instance, error)


async def _run_supervisor_for_hubspot_context(
    context: dict[str, Any],
    *,
    session_id: str,
    ticket_id: str | None = None,
    is_off_hours: bool = False,
    require_incoming: bool = False,
) -> None:
    """Run the backend-authoritative HubSpot workflow."""
    instance = await sync_to_async(ensure_conversation_instance)(
        context=context,
        ticket_id=ticket_id,
        session_id=session_id,
    )
    await _prepare_instance_for_supervisor(instance)

    incoming_prompt = build_salomao_prompt_from_hubspot_context(context)
    if require_incoming and not incoming_prompt:
        logger.info(
            "supervisor_hubspot_no_new_incoming_message",
            ticket_id=ticket_id,
            session_id=session_id,
        )
        return

    if incoming_prompt and await _waiting_turn_already_has_reply(instance):
        logger.info(
            "supervisor_hubspot_turn_already_replied",
            ticket_id=ticket_id,
            session_id=session_id,
            message_id=instance.last_message_id or None,
        )
        return

    latest_customer_text = _latest_incoming_customer_text(context)
    if latest_customer_text and await sync_to_async(handle_resolution_confirmation)(instance, latest_customer_text):
        logger.info(
            "supervisor_customer_confirmed_resolution",
            ticket_id=ticket_id,
            session_id=session_id,
        )
        return

    safe_context, content_risk_flags = _sanitize_latest_incoming_customer_text(context)
    if require_incoming:
        message = build_salomao_prompt_from_hubspot_context(safe_context)
        if not message:
            logger.info(
                "supervisor_hubspot_no_new_incoming_message",
                ticket_id=ticket_id,
                session_id=session_id,
            )
            return
    else:
        message = _build_hubspot_supervisor_message(safe_context, ticket_id)
    if not message:
        logger.info("supervisor_hubspot_no_message", ticket_id=ticket_id, session_id=session_id)
        return

    conversation_context = build_conversation_context_from_hubspot_context(
        safe_context,
        session_id=session_id,
        is_off_hours=is_off_hours,
    )
    if "prompt_injection_attempt" in content_risk_flags:
        await sync_to_async(request_human_handoff)(
            instance=instance,
            reason="Deterministic content safety policy detected an instruction-override attempt.",
            conversation_context=conversation_context,
            triage_decision=None,
            ai_summary="Conteúdo potencialmente adversarial detectado antes da execução dos agentes.",
        )
        logger.warning(
            "supervisor_content_safety_handoff",
            ticket_id=ticket_id,
            session_id=session_id,
            risk_flags=content_risk_flags,
        )
        return

    if not conversation_context.can_send_reply:
        await sync_to_async(request_human_handoff)(
            instance=instance,
            reason="Channel cannot send automated replies.",
            conversation_context=conversation_context,
            triage_decision=None,
            ai_summary="Canal incompatível com resposta automatizada.",
        )
        logger.info("supervisor_hubspot_channel_requires_handoff", ticket_id=ticket_id, session_id=session_id)
        return

    # A previous successful reply intentionally leaves the instance waiting
    # for the customer. A genuine new incoming message starts another turn and
    # must re-enter hydration before the supervisor can send its next reply.
    await _resume_waiting_instance_for_customer_message(instance)
    await _advance_lifecycle_for_hubspot_context(
        context,
        ticket_id,
        [
            ConversationInstance.State.CONTEXT_READY,
            ConversationInstance.State.TRIAGE_PENDING,
            ConversationInstance.State.TRIAGE_RUNNING,
            ConversationInstance.State.AI_SERVICE_PENDING,
            ConversationInstance.State.AI_SERVICE_RUNNING,
        ],
        reason="Supervisor worker processing HubSpot context.",
    )
    await sync_to_async(instance.refresh_from_db)()

    # Staging currently receives customer turns through a ticket-property
    # webhook, not conversation.newMessage. The hydrated history is the
    # authoritative signal: when its latest usable item is incoming, run the
    # deterministic case lookup regardless of which webhook woke the worker.
    commercial_reply = handle_commercial_contact_from_hubspot_context(safe_context) if incoming_prompt else None
    if commercial_reply is not None:
        result = _deterministic_response(
            session_id=session_id,
            message=commercial_reply,
            policy="commercial_contact",
        )
        await apply_supervisor_result(
            instance=instance,
            context=safe_context,
            conversation_context=conversation_context,
            message=message,
            result=result,
        )
        logger.info(
            "hubspot_commercial_contact_completed",
            ticket_id=ticket_id,
            session_id=session_id,
            outcome="candidate_resolved",
        )
        return

    protocol_reply = await handle_protocol_lookup_from_hubspot_context(safe_context) if incoming_prompt else None
    if protocol_reply is not None:
        result = _deterministic_response(
            session_id=session_id,
            message=protocol_reply,
            policy="protocol_lookup",
        )
        await apply_supervisor_result(
            instance=instance,
            context=safe_context,
            conversation_context=conversation_context,
            message=message,
            result=result,
        )
        logger.info(
            "hubspot_protocol_lookup_completed",
            ticket_id=ticket_id,
            session_id=session_id,
            outcome="candidate_resolved",
        )
        return

    supervisor = SalomaoSupervisorAgent(
        session_id=session_id,
        user_metadata={
            "user_id": 0,
            "hubspot_ticket_id": ticket_id or context.get("ticket_id", ""),
            "hubspot_owner_id": context.get("owner_id", ""),
            "hubspot_contact_ids": safe_context.get("contact_ids", []),
            "originating_channel": "hubspot",
            "is_off_hours": is_off_hours,
            "conversation_context": conversation_context.model_dump(mode="json"),
            "image_base64": safe_context.get("image_base64"),
            "image_mime_type": safe_context.get("image_mime_type"),
            "image_name": safe_context.get("image_name"),
        },
    )

    result = await supervisor.run_pipeline_async(message)
    await _record_usage(ticket_id or context.get("ticket_id", ""), session_id, result)
    await apply_supervisor_result(
        instance=instance,
        context=safe_context,
        conversation_context=conversation_context,
        message=message,
        result=result,
    )

    logger.info(
        "supervisor_hubspot_completed",
        ticket_id=ticket_id,
        session_id=session_id,
        tokens_used=result.tokens_used,
        requires_human_handoff=result.requires_human_handoff,
        outcome=result.decision.outcome if result.decision else "legacy",
    )


async def _run_supervisor_pipeline(
    ticket_id: str,
    is_off_hours: bool = False,
    enforce_ai_pipeline: bool = False,
) -> None:
    """Hydrate and execute the Supervisor, propagating failures to Celery."""
    context: dict[str, Any] = {}
    try:
        context = await hydrate_ticket_context(ticket_id)
        if context.get("errors") and not context.get("subject"):
            logger.error("supervisor_pipeline_aborted", ticket_id=ticket_id, errors=context["errors"])
            raise RuntimeError(f"HubSpot ticket context hydration failed: {context['errors']}")

        expected_pipeline = str(getattr(settings, "HUBSPOT_AI_TRIAGE_PIPELINE_ID", ""))
        if enforce_ai_pipeline and expected_pipeline and str(context.get("pipeline") or "") != expected_pipeline:
            logger.info(
                "supervisor_pipeline_wrong_pipeline_skipped",
                ticket_id=ticket_id,
                pipeline=context.get("pipeline"),
                expected_pipeline=expected_pipeline,
            )
            return

        thread_ids = context.get("thread_ids") or []
        session_id = f"hubspot-thread-{thread_ids[0]}" if thread_ids else f"hubspot-ticket-{ticket_id}"

        await _run_supervisor_for_hubspot_context(
            context,
            session_id=session_id,
            ticket_id=ticket_id,
            is_off_hours=is_off_hours,
        )
    except Exception as exc:
        thread_ids = context.get("thread_ids") or []
        await _mark_pipeline_failure(
            ticket_id=ticket_id,
            thread_id=str(thread_ids[0]) if thread_ids else None,
            error=exc,
        )
        logger.error(
            "supervisor_pipeline_failed",
            ticket_id=ticket_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise


async def _run_salomao_v1_thread_pipeline(
    thread_id: str,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    """Run the Supervisor for a HubSpot conversation thread event."""
    try:
        context = context or await hydrate_thread_context(thread_id)
        if context.get("errors") and not context.get("conversation_history"):
            logger.error("supervisor_thread_pipeline_aborted", thread_id=thread_id, errors=context["errors"])
            raise RuntimeError(f"HubSpot thread context hydration failed: {context['errors']}")

        ticket_id = context.get("ticket_id") or None
        session_id = f"hubspot-thread-{thread_id}"

        await _run_supervisor_for_hubspot_context(
            context,
            session_id=session_id,
            ticket_id=ticket_id,
            require_incoming=True,
        )
    except Exception as exc:
        await _mark_pipeline_failure(thread_id=thread_id, error=exc)
        logger.error(
            "supervisor_thread_pipeline_failed",
            thread_id=thread_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/hubspot/ticket-change",
    response={202: WebhookAcceptedResponse, 401: WebhookRejectedResponse, 422: WebhookRejectedResponse},
    auth=None,
    summary="Webhook HubSpot — mudança em ticket",
)
async def hubspot_ticket_change(
    request: HttpRequest,
    payload: list[dict[str, Any]],
) -> tuple[int, WebhookAcceptedResponse | WebhookRejectedResponse]:
    """Recebe mudança em ticket do HubSpot e dispara o Supervisor em background.

    Garantias:
        - Resposta em < 200ms (sem esperar LLM/HTTP externo).
        - Nunca executa o Supervisor fora do horário comercial ou na
          'Quinta Fire' — nestes casos, apenas a rotina de fora-de-horário
          é agendada.
        - Todo trabalho real roda em uma task do Celery, isolado do HTTP.
    """
    if not _signature_ok(request):
        logger.warning(
            "hubspot_webhook_signature_invalid",
            v1=request.headers.get("X-HubSpot-Signature", ""),
            v3=request.headers.get("X-HubSpot-Signature-v3", ""),
        )
        return 401, WebhookRejectedResponse(
            detail="Assinatura HubSpot inválida.",
            error_code="INVALID_SIGNATURE",
        )

    ticket_id = _extract_ticket_id(payload)
    if ticket_id is None:
        logger.warning("hubspot_webhook_missing_ticket_id", payload_preview=str(payload)[:200])
        return 422, WebhookRejectedResponse(
            detail="Payload sem objectId (ticket_id).",
            error_code="MISSING_TICKET_ID",
        )

    reason = off_hours_reason()
    is_off_hours = reason is not None or is_quinta_fire() or not is_business_hours()

    if not getattr(settings, "AI_ROUTING_ENABLED", False):
        # Secondary safety net: even if this router is mounted, never fire the
        # supervisor pipeline unless the AI flag is explicitly on. The primary
        # gate lives in core/urls.py (the router is not mounted at all), but
        # this keeps the contract defensive if someone mounts it directly.
        logger.info("hubspot_webhook_ai_routing_disabled", ticket_id=ticket_id)
        return 202, WebhookAcceptedResponse(
            status="accepted_ai_disabled",
            ticket_id=ticket_id,
            routed_to="noop",
        )

    run_supervisor_pipeline_task.delay(ticket_id, is_off_hours)
    logger.info("hubspot_webhook_supervisor_dispatched", ticket_id=ticket_id, is_off_hours=is_off_hours)

    return 202, WebhookAcceptedResponse(
        status="accepted",
        ticket_id=ticket_id,
        routed_to="supervisor_pipeline",
    )


__all__ = ["router"]
