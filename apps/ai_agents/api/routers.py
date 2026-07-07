"""Django Ninja API routers for AI Agents — Salomão Supervisor endpoints.

This module exposes the SalomaoSupervisorAgent via RESTful endpoints,
providing authenticated chat functionality with proper error handling,
timeout management, and structured logging.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from ninja import Router, Schema
from pydantic import BaseModel

from apps.ai_agents.agents.supervisor import SalomaoResponse, SalomaoSupervisorAgent
from common.exceptions import ExternalServiceError

if TYPE_CHECKING:
    from apps.auth_user.models import User


class AuthenticatedRequest(Protocol):
    """Protocol for Django Ninja's authenticated request (JWTAuth injects request.auth)."""

    auth: User


router = Router()
logger = structlog.get_logger(__name__)


class ChatRequest(BaseModel):
    """Schema Pydantic para requisições de chat com o Salomão.

    Attributes:
        message: Mensagem do usuário para processamento pelo agente.
    """

    message: str


class ChatSuccessResponse(Schema):
    """Resposta bem-sucedida do endpoint de chat.

    Schema Ninja para serialização consistente da resposta do SalomaoSupervisorAgent.
    """

    session_id: str
    message: str
    sources: list[dict[str, Any]]
    requires_human_handoff: bool
    handoff_reason: str | None
    agent_trace: list[str]
    tokens_used: int
    latency_ms: int


class ErrorResponse(Schema):
    """Schema padronizado para respostas de erro."""

    detail: str
    error_code: str | None = None


@router.post(
    "/chat",
    response={200: ChatSuccessResponse, 503: ErrorResponse, 504: ErrorResponse},
    summary="Chat com o Salomão (Supervisor Multi-Agente)",
)
async def chat_with_salomao(
    request: AuthenticatedRequest,
    payload: ChatRequest,
) -> tuple[int, ChatSuccessResponse | ErrorResponse]:
    """Processa mensagem do usuário autenticado via SalomaoSupervisorAgent.

    Este endpoint instancia o supervisor multi-agente com os metadados do usuário
    autenticado (via JWT), executa o pipeline de processamento e retorna a
    resposta estruturada. Timeout errors do Agno resultam em 503/504 conforme
    apropriado.

    Args:
        request: HttpRequest com usuário autenticado em request.auth (Ninja JWT).
        payload: ChatRequest contendo a mensagem do usuário.

    Returns:
        Tupla (status_code, response) onde response é ChatSuccessResponse em
        caso de sucesso ou ErrorResponse em caso de timeout/falha.
    """
    user = request.auth
    user_id: int = getattr(user, "pk", 0)

    session_id = f"user-{user_id}"

    user_metadata: dict[str, Any] = {
        "user_id": user_id,
        "username": getattr(user, "username", ""),
        "email": getattr(user, "email", ""),
        "first_name": getattr(user, "first_name", ""),
        "last_name": getattr(user, "last_name", ""),
        "church_id": getattr(user, "church_id", "") if hasattr(user, "church_id") else "",
        "hubspot_contact_id": "",
        "originating_channel": "api",
    }

    logger.info(
        "chat_request_received",
        session_id=session_id,
        user_id=user_id,
        message_preview=payload.message[:80],
    )

    start_time = time.perf_counter()

    try:
        supervisor = SalomaoSupervisorAgent(
            session_id=session_id,
            user_metadata=user_metadata,
        )
    except Exception as exc:
        logger.error(
            "supervisor_initialization_failed",
            session_id=session_id,
            error=str(exc),
        )
        raise ExternalServiceError("ai_agent", "Failed to initialize AI supervisor.") from exc

    try:
        # Executa pipeline de forma assíncrona para suportar MCP tools async
        result: SalomaoResponse = await supervisor.run_pipeline_async(payload.message)
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "chat_request_completed",
            session_id=session_id,
            user_id=user_id,
            latency_ms=latency_ms,
            tokens_used=result.tokens_used,
            requires_human_handoff=result.requires_human_handoff,
        )

        response_data = ChatSuccessResponse(
            session_id=result.session_id,
            message=result.message,
            sources=result.sources,
            requires_human_handoff=result.requires_human_handoff,
            handoff_reason=result.handoff_reason,
            agent_trace=result.agent_trace,
            tokens_used=result.tokens_used,
            latency_ms=result.latency_ms,
        )
        return 200, response_data

    except TimeoutError as exc:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error(
            "chat_timeout_error",
            session_id=session_id,
            user_id=user_id,
            latency_ms=latency_ms,
            error=str(exc),
        )
        return 503, ErrorResponse(
            detail="O agente demorou muito para responder. Tente novamente em alguns instantes.",
            error_code="AGENT_TIMEOUT",
        )

    except Exception as exc:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        error_msg = str(exc).lower()

        if any(timeout_kw in error_msg for timeout_kw in ("timeout", "timed out", "tempo esgotado")):
            logger.error(
                "chat_timeout_detected",
                session_id=session_id,
                user_id=user_id,
                latency_ms=latency_ms,
                error=str(exc),
            )
            return 503, ErrorResponse(
                detail="O agente demorou muito para responder. Tente novamente em alguns instantes.",
                error_code="AGENT_TIMEOUT",
            )

        if (
            "rate limit" in error_msg
            or "too many requests" in error_msg
            or "insufficient_quota" in error_msg
            or "exceeded your current quota" in error_msg
        ):
            logger.error(
                "chat_rate_limit_error",
                session_id=session_id,
                user_id=user_id,
                latency_ms=latency_ms,
                error=str(exc),
            )
            return 503, ErrorResponse(
                detail="Serviço temporariamente indisponível devido a alta demanda. Tente novamente em breve.",
                error_code="RATE_LIMIT",
            )

        logger.error(
            "chat_unexpected_error",
            session_id=session_id,
            user_id=user_id,
            latency_ms=latency_ms,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise ExternalServiceError("ai_agent", f"AI agent processing failed: {exc}") from exc
