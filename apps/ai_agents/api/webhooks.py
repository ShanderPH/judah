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
import hmac
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from ninja import Router, Schema

from apps.ai_agents.agents.supervisor import SalomaoResponse, SalomaoSupervisorAgent
from apps.ai_agents.models import AgentRun, ConversationInstance, TokenTrackingLog, ToolCallAuditLog
from apps.ai_agents.services.handoff import build_handoff_package
from apps.ai_agents.services.hubspot import (
    USE_MOCK_HUBSPOT,
    build_conversation_context_from_hubspot_context,
    build_salomao_prompt_from_hubspot_context,
    hydrate_thread_context,
    hydrate_ticket_context,
    send_salomao_reply_to_hubspot_thread,
    update_hubspot_ticket_stage,
)
from apps.ai_agents.services.lifecycle import InvalidStateTransitionError, LifecycleEngine, is_lifecycle_schema_ready
from apps.ai_agents.services.protocol_lookup import handle_protocol_lookup_from_hubspot_context
from apps.ai_agents.tasks import run_supervisor_pipeline_task
from apps.ai_agents.utils.business_rules import (
    is_business_hours,
    is_quinta_fire,
    off_hours_reason,
)
from apps.ai_agents.utils.pricing import calculate_cost

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = structlog.get_logger(__name__)

router = Router()


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
    signature = request.headers.get("X-HubSpot-Signature", "")
    if not signature:
        return False
    body = request.body.decode("utf-8")
    expected = hashlib.sha256((secret + body).encode("utf-8")).hexdigest()
    return hmac.compare_digest(signature, expected)


def _verify_signature_v3(request: HttpRequest, secret: str) -> bool:
    """HubSpot v3: HMAC-SHA256(timestamp + method + uri + body), base64."""
    signature = request.headers.get("X-HubSpot-Signature-v3", "")
    timestamp = request.headers.get("X-HubSpot-Request-Timestamp", "")
    if not signature or not timestamp:
        return False
    method = (request.method or "POST").upper()
    url = request.build_absolute_uri()
    body = request.body.decode("utf-8")
    source = f"{timestamp}{method}{url}{body}"
    expected = hmac.new(
        secret.encode("utf-8"),
        source.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


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
    return _verify_signature_v1(request, secret) or _verify_signature_v3(request, secret)


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
    """Persist one agent run and every stateful HubSpot effect for the turn."""
    if not is_lifecycle_schema_ready():
        logger.warning("hubspot_turn_audit_schema_missing", ticket_id=ticket_id, session_id=session_id)
        return
    thread_ids = context.get("thread_ids") or []
    instance = None
    if thread_ids:
        instance = ConversationInstance.objects.filter(hubspot_thread_id=str(thread_ids[0])).first()
    if instance is None and ticket_id:
        instance = ConversationInstance.objects.filter(hubspot_ticket_id=str(ticket_id)).first()
    if instance is None:
        return

    history = context.get("conversation_history") or []
    latest_incoming = next(
        (item for item in reversed(history) if str(item.get("direction") or "").upper() == "INCOMING"),
        {},
    )
    turn_source = str(latest_incoming.get("id") or latest_incoming.get("created_at") or session_id)
    turn_key = hashlib.sha256(turn_source.encode("utf-8")).hexdigest()[:20]
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
    elif any("heimdall: failed" in str(item) for item in output_structured.get("agent_trace") or []):
        engine.record_agent_run(
            instance=instance,
            agent_name="HeimdallTriageAgent",
            input_snapshot={"session_id": session_id, "message_id": latest_incoming.get("id")},
            status=AgentRun.Status.FAILED,
            error_message="Heimdall triage failed; Supervisor selected safe human handoff.",
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
    elif any("salomao_chat: failed" in str(item) for item in trace):
        engine.record_agent_run(
            instance=instance,
            agent_name="SalomaoChatAgent",
            input_snapshot={"session_id": session_id, "message_id": latest_incoming.get("id")},
            status=AgentRun.Status.FAILED,
            error_message=str(output_structured.get("handoff_reason") or "Salomao adapter failed."),
        )

    effects = (
        ("update_ticket_stage_active", active_stage_result, "updated"),
        ("send_thread_reply", reply_result, "sent"),
        ("update_ticket_stage_final", final_stage_result, "updated"),
    )
    for tool_name, effect_result, success_field in effects:
        succeeded = bool(effect_result.get(success_field))
        engine.record_tool_call(
            instance=instance,
            agent_run=agent_run,
            tool_name=tool_name,
            idempotency_key=f"{instance.pk}:{turn_key}:{tool_name}",
            input_payload={"ticket_id": ticket_id, "session_id": session_id},
            output_payload=effect_result,
            status=ToolCallAuditLog.Status.SUCCEEDED if succeeded else ToolCallAuditLog.Status.FAILED,
            external_object_type="hubspot_ticket" if "stage" in tool_name else "hubspot_thread",
            external_object_id=str(ticket_id or (thread_ids[0] if thread_ids else "")),
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
    instance = None
    if thread_ids:
        instance = ConversationInstance.objects.filter(hubspot_thread_id=str(thread_ids[0])).first()
    if instance is None and ticket_id:
        instance = ConversationInstance.objects.filter(hubspot_ticket_id=str(ticket_id)).first()
    if instance is None and context.get("ticket_id"):
        instance = ConversationInstance.objects.filter(hubspot_ticket_id=str(context["ticket_id"])).first()
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


async def _move_hubspot_ticket(
    ticket_id: str | None,
    stage_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    """Best-effort deterministic ticket transition around an AI turn."""
    if not ticket_id or not stage_id:
        return {"updated": False, "reason": "missing_ticket_or_stage"}

    result = await update_hubspot_ticket_stage(str(ticket_id), str(stage_id))
    if not result.get("updated"):
        logger.error(
            "supervisor_hubspot_stage_transition_failed",
            ticket_id=ticket_id,
            stage_id=stage_id,
            transition_reason=reason,
            provider_reason=result.get("reason"),
        )
    return result


async def _run_supervisor_for_hubspot_context(
    context: dict[str, Any],
    *,
    session_id: str,
    ticket_id: str | None = None,
    is_off_hours: bool = False,
    require_incoming: bool = False,
) -> None:
    """Run the Supervisor from HubSpot context and send its answer back to HubSpot."""
    effective_ticket_id = str(ticket_id or context.get("ticket_id") or "") or None
    message = build_salomao_prompt_from_hubspot_context(context) if require_incoming else None
    message = message or _build_hubspot_supervisor_message(context, ticket_id)
    if not message:
        logger.info("supervisor_hubspot_no_message", ticket_id=ticket_id, session_id=session_id)
        return

    active_stage = str(getattr(settings, "HUBSPOT_AI_TRIAGE_STAGE_ID", ""))
    active_stage_result = await _move_hubspot_ticket(
        effective_ticket_id,
        active_stage,
        reason="ai_turn_started",
    )

    conversation_context = build_conversation_context_from_hubspot_context(
        context,
        session_id=session_id,
        is_off_hours=is_off_hours,
    )
    if not conversation_context.can_send_reply:
        await _move_hubspot_ticket(
            effective_ticket_id,
            str(getattr(settings, "HUBSPOT_HUMAN_ESCALATION_STAGE_ID", "")),
            reason="channel_cannot_reply",
        )
        await _advance_lifecycle_for_hubspot_context(
            context,
            ticket_id,
            [ConversationInstance.State.HUMAN_HANDOFF_REQUESTED],
            reason="Channel cannot send automated replies.",
        )
        logger.info("supervisor_hubspot_channel_requires_handoff", ticket_id=ticket_id, session_id=session_id)
        return

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

    protocol_reply = await handle_protocol_lookup_from_hubspot_context(context) if require_incoming else None
    if protocol_reply is not None:
        reply_result = await send_salomao_reply_to_hubspot_thread(context, protocol_reply)
        if reply_result.get("sent"):
            final_stage_result = await _move_hubspot_ticket(
                effective_ticket_id,
                str(getattr(settings, "HUBSPOT_AI_WAITING_STAGE_ID", "")),
                reason="protocol_reply_sent",
            )
            await _advance_lifecycle_for_hubspot_context(
                context,
                ticket_id,
                [ConversationInstance.State.WAITING_FOR_CUSTOMER],
                reason="Judah answered a HubSpot protocol lookup.",
            )
        else:
            final_stage_result = await _move_hubspot_ticket(
                effective_ticket_id,
                str(getattr(settings, "HUBSPOT_HUMAN_ESCALATION_STAGE_ID", "")),
                reason="protocol_reply_failed",
            )
            await _advance_lifecycle_for_hubspot_context(
                context,
                ticket_id,
                [ConversationInstance.State.HUMAN_HANDOFF_REQUESTED],
                reason=reply_result.get("reason") or "Judah could not send the protocol lookup reply.",
            )
        await _record_hubspot_turn_audit(
            context=context,
            ticket_id=effective_ticket_id,
            session_id=session_id,
            agent_name="ProtocolLookupService",
            output_structured={"message": protocol_reply, "outcome": "waiting_customer"},
            reply_result=reply_result,
            active_stage_result=active_stage_result,
            final_stage_result=final_stage_result,
            conversation_context=conversation_context,
            handoff_reason=None if reply_result.get("sent") else reply_result.get("reason") or "reply_failed",
        )
        logger.info(
            "hubspot_protocol_lookup_completed",
            ticket_id=ticket_id,
            session_id=session_id,
            reply_sent=reply_result.get("sent"),
            reply_reason=reply_result.get("reason"),
            active_stage_updated=active_stage_result.get("updated"),
            final_stage_updated=final_stage_result.get("updated"),
        )
        return

    supervisor = SalomaoSupervisorAgent(
        session_id=session_id,
        user_metadata={
            "user_id": 0,
            "hubspot_ticket_id": ticket_id or context.get("ticket_id", ""),
            "hubspot_owner_id": context.get("owner_id", ""),
            "hubspot_contact_ids": context.get("contact_ids", []),
            "originating_channel": "hubspot",
            "is_off_hours": is_off_hours,
            "conversation_context": conversation_context.model_dump(mode="json"),
            "image_base64": context.get("image_base64"),
            "image_mime_type": context.get("image_mime_type"),
        },
    )

    result = await supervisor.run_pipeline_async(message)
    reply_result = await send_salomao_reply_to_hubspot_thread(context, result.message)
    await _record_usage(ticket_id or context.get("ticket_id", ""), session_id, result)

    requires_handoff = result.requires_human_handoff or result.outcome in {"escalate_human", "failed"}
    if requires_handoff or not reply_result.get("sent"):
        final_stage_result = await _move_hubspot_ticket(
            effective_ticket_id,
            str(getattr(settings, "HUBSPOT_HUMAN_ESCALATION_STAGE_ID", "")),
            reason="human_handoff_or_reply_failed",
        )
        await _advance_lifecycle_for_hubspot_context(
            context,
            ticket_id,
            [ConversationInstance.State.HUMAN_HANDOFF_REQUESTED],
            reason=result.handoff_reason or reply_result.get("reason") or "Supervisor requested handoff.",
        )
    else:
        final_stage_result = await _move_hubspot_ticket(
            effective_ticket_id,
            str(getattr(settings, "HUBSPOT_AI_WAITING_STAGE_ID", "")),
            reason="ai_reply_sent",
        )
        await _advance_lifecycle_for_hubspot_context(
            context,
            ticket_id,
            [ConversationInstance.State.WAITING_FOR_CUSTOMER],
            reason="Supervisor sent an answer and is waiting for the customer.",
        )

    await _record_hubspot_turn_audit(
        context=context,
        ticket_id=effective_ticket_id,
        session_id=session_id,
        agent_name="SalomaoSupervisorAgent",
        output_structured=result.model_dump(mode="json"),
        reply_result=reply_result,
        active_stage_result=active_stage_result,
        final_stage_result=final_stage_result,
        conversation_context=conversation_context,
        triage_decision=result.triage_decision,
        handoff_reason=(
            result.handoff_reason or reply_result.get("reason") or "Supervisor requested handoff."
            if requires_handoff or not reply_result.get("sent")
            else None
        ),
        tokens_used=result.tokens_used,
        latency_ms=result.latency_ms,
    )

    logger.info(
        "supervisor_hubspot_completed",
        ticket_id=ticket_id,
        session_id=session_id,
        reply_sent=reply_result.get("sent"),
        reply_reason=reply_result.get("reason"),
        tokens_used=result.tokens_used,
        requires_human_handoff=result.requires_human_handoff,
        outcome=result.outcome,
        active_stage_updated=active_stage_result.get("updated"),
        final_stage_updated=final_stage_result.get("updated"),
    )


async def _run_supervisor_pipeline(
    ticket_id: str,
    is_off_hours: bool = False,
    enforce_ai_pipeline: bool = False,
) -> None:
    """Hidrata o contexto e executa o Supervisor — roda desconectado do HTTP.

    Qualquer exceção é capturada e logada; nunca sobe (senão o asyncio imprime
    'Task exception was never retrieved' no stdout do worker).
    """
    try:
        context = await hydrate_ticket_context(ticket_id)
        if context.get("errors") and not context.get("subject"):
            logger.error("supervisor_pipeline_aborted", ticket_id=ticket_id, errors=context["errors"])
            return

        expected_pipeline = str(getattr(settings, "HUBSPOT_AI_TRIAGE_PIPELINE_ID", ""))
        if enforce_ai_pipeline and expected_pipeline and str(context.get("pipeline") or "") != expected_pipeline:
            logger.info(
                "supervisor_pipeline_wrong_pipeline_skipped",
                ticket_id=ticket_id,
                pipeline=context.get("pipeline"),
                expected_pipeline=expected_pipeline,
            )
            return

        session_id = f"hubspot-ticket-{ticket_id}"

        await _run_supervisor_for_hubspot_context(
            context,
            session_id=session_id,
            ticket_id=ticket_id,
            is_off_hours=is_off_hours,
        )
    except Exception as exc:
        logger.error(
            "supervisor_pipeline_failed",
            ticket_id=ticket_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def _run_salomao_v1_thread_pipeline(thread_id: str) -> None:
    """Run the Supervisor for a HubSpot conversation thread event."""
    try:
        context = await hydrate_thread_context(thread_id)
        if context.get("errors") and not context.get("conversation_history"):
            logger.error("supervisor_thread_pipeline_aborted", thread_id=thread_id, errors=context["errors"])
            return

        ticket_id = context.get("ticket_id") or None
        if ticket_id:
            ticket_context = await hydrate_ticket_context(str(ticket_id))
            ticket_context["thread_ids"] = context.get("thread_ids") or ticket_context.get("thread_ids") or []
            ticket_context["threads"] = context.get("threads") or ticket_context.get("threads") or []
            ticket_context["conversation_history"] = (
                context.get("conversation_history") or ticket_context.get("conversation_history") or []
            )
            for image_key in ("image_base64", "image_mime_type", "image_name"):
                if context.get(image_key):
                    ticket_context[image_key] = context[image_key]
            context = ticket_context

            expected_pipeline = str(getattr(settings, "HUBSPOT_AI_TRIAGE_PIPELINE_ID", ""))
            if expected_pipeline and str(context.get("pipeline") or "") != expected_pipeline:
                logger.info(
                    "supervisor_thread_wrong_pipeline_skipped",
                    thread_id=thread_id,
                    ticket_id=ticket_id,
                    pipeline=context.get("pipeline"),
                    expected_pipeline=expected_pipeline,
                )
                return
        session_id = f"hubspot-ticket-{ticket_id}" if ticket_id else f"hubspot-thread-{thread_id}"

        await _run_supervisor_for_hubspot_context(
            context,
            session_id=session_id,
            ticket_id=ticket_id,
            require_incoming=True,
        )
    except Exception as exc:
        logger.error(
            "supervisor_thread_pipeline_failed",
            thread_id=thread_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


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
