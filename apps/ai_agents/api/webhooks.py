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
from apps.ai_agents.models import TokenTrackingLog
from apps.ai_agents.services.hubspot import (
    USE_MOCK_HUBSPOT,
    build_salomao_prompt_from_hubspot_context,
    hydrate_thread_context,
    hydrate_ticket_context,
    send_salomao_reply_to_hubspot_thread,
)
from apps.ai_agents.tasks import run_supervisor_pipeline_task
from apps.ai_agents.utils.business_rules import (
    is_business_hours,
    is_quinta_fire,
    off_hours_reason,
)
from apps.ai_agents.utils.pricing import calculate_cost
from apps.integrations.salomao_v1 import SalomaoV1ChatResult, is_salomao_v1_configured, send_chat_to_salomao_v1

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


async def _record_salomao_v1_usage(ticket_id: str | None, session_id: str, result: SalomaoV1ChatResult) -> None:
    """Persist best-effort token usage returned by Salomao v1."""
    if result.tokens.total <= 0:
        return

    try:
        await _persist_token_tracking(
            session_id=session_id,
            ticket_id=ticket_id,
            model_name=result.model_used or "salomao-v1",
            prompt_tokens=result.tokens.prompt,
            completion_tokens=result.tokens.completion,
            cost_usd=0.0,
        )
    except Exception as exc:
        logger.error(
            "salomao_v1_token_tracking_failed",
            ticket_id=ticket_id,
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def _run_salomao_v1_for_hubspot_context(
    context: dict[str, Any],
    *,
    session_id: str,
    ticket_id: str | None = None,
) -> None:
    """Call Salomao v1 from HubSpot context and send its answer back to HubSpot."""
    message = build_salomao_prompt_from_hubspot_context(context)
    if not message:
        logger.info("salomao_v1_hubspot_no_incoming_message", ticket_id=ticket_id, session_id=session_id)
        return

    result = await send_chat_to_salomao_v1(
        message=message,
        session_id=session_id,
    )
    reply_result = await send_salomao_reply_to_hubspot_thread(context, result.response)
    await _record_salomao_v1_usage(ticket_id, session_id, result)

    logger.info(
        "salomao_v1_hubspot_completed",
        ticket_id=ticket_id,
        session_id=session_id,
        reply_sent=reply_result.get("sent"),
        reply_reason=reply_result.get("reason"),
        tokens_used=result.tokens.total,
        transfer_requested=result.transfer_requested,
    )


async def _run_supervisor_pipeline(ticket_id: str, is_off_hours: bool = False) -> None:
    """Hidrata o contexto e executa o Supervisor — roda desconectado do HTTP.

    Qualquer exceção é capturada e logada; nunca sobe (senão o asyncio imprime
    'Task exception was never retrieved' no stdout do worker).
    """
    try:
        context = await hydrate_ticket_context(ticket_id)
        if context.get("errors") and not context.get("subject"):
            logger.error("supervisor_pipeline_aborted", ticket_id=ticket_id, errors=context["errors"])
            return

        session_id = f"hubspot-ticket-{ticket_id}"

        if is_salomao_v1_configured():
            await _run_salomao_v1_for_hubspot_context(
                context,
                session_id=session_id,
                ticket_id=ticket_id,
            )
            return

        user_metadata: dict[str, Any] = {
            "user_id": 0,
            "hubspot_ticket_id": ticket_id,
            "hubspot_owner_id": context.get("owner_id", ""),
            "hubspot_contact_ids": context.get("contact_ids", []),
            "originating_channel": context.get("originating_channel", ""),
            "is_off_hours": is_off_hours,
        }

        supervisor = SalomaoSupervisorAgent(
            session_id=session_id,
            user_metadata=user_metadata,
        )

        # Mensagem passada ao pipeline: assunto + conteúdo do ticket como
        # fallback quando não há histórico de conversa.
        history_lines = [
            f"[{m.get('direction')}] {m.get('text')}" for m in context.get("conversation_history", []) if m.get("text")
        ]
        history_block = "\n".join(history_lines) or context.get("content", "")
        message = (
            f"Ticket HubSpot #{ticket_id}\n"
            f"Assunto: {context.get('subject', '(sem assunto)')}\n"
            f"Canal: {context.get('originating_channel', 'desconhecido')}\n\n"
            f"Conteúdo / Histórico:\n{history_block}"
        )

        result = await supervisor.run_pipeline_async(message)
        logger.info(
            "supervisor_pipeline_completed",
            ticket_id=ticket_id,
            session_id=session_id,
            requires_human_handoff=result.requires_human_handoff,
            tokens_used=result.tokens_used,
            latency_ms=result.latency_ms,
        )
        await _record_usage(ticket_id, session_id, result)
    except Exception as exc:
        logger.error(
            "supervisor_pipeline_failed",
            ticket_id=ticket_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def _run_salomao_v1_thread_pipeline(thread_id: str) -> None:
    """Run Salomao v1 for a HubSpot conversation thread event."""
    try:
        context = await hydrate_thread_context(thread_id)
        if context.get("errors") and not context.get("conversation_history"):
            logger.error("salomao_v1_thread_pipeline_aborted", thread_id=thread_id, errors=context["errors"])
            return

        ticket_id = context.get("ticket_id") or None
        session_id = f"hubspot-ticket-{ticket_id}" if ticket_id else f"hubspot-thread-{thread_id}"

        await _run_salomao_v1_for_hubspot_context(
            context,
            session_id=session_id,
            ticket_id=ticket_id,
        )
    except Exception as exc:
        logger.error(
            "salomao_v1_thread_pipeline_failed",
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
