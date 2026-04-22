"""HubSpot MCP Server — Ferramentas para HelpdeskActionAgent.

Servidor MCP (Model Context Protocol) usando FastMCP para expor
funcionalidades do HubSpot CRM ao agente de helpdesk Salomão.

Ferramentas disponíveis:
  - get_ticket_status: Consulta status de um ticket existente
  - create_helpdesk_ticket: Cria um novo ticket de suporte

Isolamento: Este arquivo NÃO importa Django. Usa variáveis de ambiente.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog
from mcp.server.fastmcp import FastMCP

# Carrega .env se existir (para desenvolvimento local).
# Âncora explícita ao diretório raiz do projeto, relativo a este arquivo,
# garantindo que o subprocesso stdio encontre o .env independente do CWD.
try:
    from pathlib import Path

    from dotenv import load_dotenv

    _dotenv_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    load_dotenv(_dotenv_path)
except ImportError:
    pass  # dotenv é opcional, produção usa env vars reais

logger = structlog.get_logger(__name__)

mcp = FastMCP("hubspot")

HUBSPOT_API_BASE = "https://api.hubapi.com"


def _get_hubspot_token() -> str:
    """Recupera o token de acesso do HubSpot via variável de ambiente.

    Returns:
        Token de acesso OAuth do HubSpot.

    Raises:
        RuntimeError: Se o token não estiver configurado.
    """
    token = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("HUBSPOT_ACCESS_TOKEN não configurado. Defina a variável de ambiente HUBSPOT_ACCESS_TOKEN.")
    return token


def _build_headers() -> dict[str, str]:
    """Constrói headers padrão para requisições HubSpot.

    Returns:
        Dict com Authorization e Content-Type.
    """
    return {
        "Authorization": f"Bearer {_get_hubspot_token()}",
        "Content-Type": "application/json",
    }


@mcp.tool()
async def get_ticket_status(ticket_id: str) -> dict[str, Any] | str:
    """Consulta o status de um ticket no HubSpot.

    Args:
        ticket_id: ID numérico do ticket no HubSpot (ex: "123456789").

    Returns:
        Dict com informações do ticket ou mensagem de erro em string.
        Campos retornados: id, subject, status, priority, stage, owner_id,
        created_at, last_activity_at.

    Example:
        >>> result = await get_ticket_status("123456789")
        >>> print(result)
        {
            "id": "123456789",
            "subject": "Problema com login",
            "status": "open",
            "priority": "HIGH",
            "stage": "1",
            "owner_id": "12345",
            "created_at": "2024-01-15T10:30:00Z",
            "last_activity_at": "2024-01-15T14:20:00Z"
        }
    """
    url = f"{HUBSPOT_API_BASE}/crm/v3/objects/tickets/{ticket_id}"
    headers = _build_headers()

    properties = [
        "subject",
        "content",
        "hs_ticket_priority",
        "hs_pipeline",
        "hs_pipeline_stage",
        "hubspot_owner_id",
        "createdate",
        "hs_lastactivitydate",
        "hs_ticket_category",
        "hs_ticket_id",
    ]

    params = {"properties": ",".join(properties)}

    logger.info("hubspot_get_ticket_start", ticket_id=ticket_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            props = data.get("properties", {})

            result = {
                "id": data.get("id"),
                "subject": props.get("subject", ""),
                "content": props.get("content", ""),
                "status": _map_stage_to_status(props.get("hs_pipeline_stage", "")),
                "priority": props.get("hs_ticket_priority", ""),
                "stage": props.get("hs_pipeline_stage", ""),
                "pipeline": props.get("hs_pipeline", ""),
                "owner_id": props.get("hubspot_owner_id", ""),
                "category": props.get("hs_ticket_category", ""),
                "created_at": props.get("createdate", ""),
                "last_activity_at": props.get("hs_lastactivitydate", ""),
            }

            logger.info(
                "hubspot_get_ticket_success",
                ticket_id=ticket_id,
                status=result["status"],
                priority=result["priority"],
            )
            return result

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            error_msg = f"Erro HTTP {status_code} ao buscar ticket {ticket_id}"

            if status_code == 404:
                error_msg = f"Ticket {ticket_id} não encontrado no HubSpot"
            elif status_code == 401:
                error_msg = "Erro de autenticação com HubSpot"
            elif status_code == 429:
                error_msg = "Limite de requisições HubSpot excedido (rate limit)"

            logger.error(
                "hubspot_get_ticket_http_error",
                ticket_id=ticket_id,
                status_code=status_code,
                error=str(exc),
            )
            return {"error": error_msg, "status_code": status_code}

        except httpx.TimeoutException as exc:
            logger.error("hubspot_get_ticket_timeout", ticket_id=ticket_id, error=str(exc))
            return {"error": f"Timeout ao consultar ticket {ticket_id}. Tente novamente.", "status_code": 504}

        except Exception as exc:
            logger.error("hubspot_get_ticket_error", ticket_id=ticket_id, error=str(exc))
            return {"error": f"Erro inesperado: {exc!s}", "status_code": 500}


@mcp.tool()
async def create_helpdesk_ticket(
    user_id: str,
    issue_description: str,
    urgency: int = 2,
) -> dict[str, Any] | str:
    """Cria um novo ticket de suporte no HubSpot.

    Args:
        user_id: ID do usuário afetado (pode ser email ou ID interno).
        issue_description: Descrição detalhada do problema ou solicitação.
        urgency: Nível de urgência de 1 a 4 (1=URGENTE, 2=ALTA, 3=MÉDIA, 4=BAIXA).
               Default é 2 (ALTA).

    Returns:
        Dict com dados do ticket criado ou mensagem de erro.
        Campos retornados: id, subject, status, priority, created_at, url.

    Example:
        >>> result = await create_helpdesk_ticket(
        ...     user_id="usuario@igreja.com",
        ...     issue_description="Não consigo acessar o painel administrativo",
        ...     urgency=1
        ... )
        >>> print(result)
        {
            "id": "987654321",
            "subject": "Não consigo acessar o painel administrativo",
            "status": "new",
            "priority": "URGENT",
            "created_at": "2024-01-15T16:45:00Z",
            "url": "https://app.hubspot.com/contacts/.../ticket/987654321"
        }
    """
    url = f"{HUBSPOT_API_BASE}/crm/v3/objects/tickets"
    headers = _build_headers()

    priority_map = {
        1: "URGENT",
        2: "HIGH",
        3: "MEDIUM",
        4: "LOW",
    }
    priority = priority_map.get(urgency, "MEDIUM")

    subject = issue_description[:100] if len(issue_description) > 100 else issue_description

    payload: dict[str, Any] = {
        "properties": {
            "subject": subject,
            "content": issue_description,
            "hs_ticket_priority": priority,
            "hs_pipeline": "0",
            "hs_pipeline_stage": "1",
            "hs_ticket_category": "OTHER",
            "source_type": "INTERNAL",
        }
    }

    if "@" in user_id:
        contact_id = await _resolve_contact_by_email(user_id)
        if contact_id:
            payload["associations"] = [
                {
                    "to": {"id": contact_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 16}],
                }
            ]

    logger.info(
        "hubspot_create_ticket_start",
        user_id=user_id,
        priority=priority,
        subject_preview=subject[:50],
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            props = data.get("properties", {})
            ticket_id = data.get("id")

            result = {
                "id": ticket_id,
                "subject": props.get("subject", ""),
                "content": props.get("content", ""),
                "status": "new",
                "priority": props.get("hs_ticket_priority", ""),
                "stage": props.get("hs_pipeline_stage", ""),
                "pipeline": props.get("hs_pipeline", ""),
                "created_at": props.get("createdate", ""),
                "url": f"https://app.hubspot.com/contacts/{_get_portal_id()}/ticket/{ticket_id}/"
                if ticket_id
                else None,
            }

            logger.info(
                "hubspot_create_ticket_success",
                ticket_id=ticket_id,
                user_id=user_id,
                priority=result["priority"],
            )
            return result

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            error_detail = exc.response.text[:200]

            error_msg = f"Erro HTTP {status_code} ao criar ticket"
            if status_code == 400:
                error_msg = f"Dados inválidos para criação do ticket: {error_detail}"
            elif status_code == 401:
                error_msg = "Erro de autenticação com HubSpot"
            elif status_code == 429:
                error_msg = "Limite de requisições HubSpot excedido (rate limit)"
            elif status_code == 409:
                error_msg = "Conflito: ticket similar já existe"

            logger.error(
                "hubspot_create_ticket_http_error",
                user_id=user_id,
                status_code=status_code,
                error=error_detail,
            )
            return {"error": error_msg, "status_code": status_code}

        except httpx.TimeoutException as exc:
            logger.error("hubspot_create_ticket_timeout", user_id=user_id, error=str(exc))
            return {
                "error": "Timeout ao criar ticket. O ticket pode ter sido criado — verifique no HubSpot.",
                "status_code": 504,
            }

        except Exception as exc:
            logger.error("hubspot_create_ticket_error", user_id=user_id, error=str(exc))
            return {"error": f"Erro inesperado ao criar ticket: {exc!s}", "status_code": 500}


@mcp.tool()
async def update_ticket(
    ticket_id: str,
    pipeline_stage: str | None = None,
    reply_note: str | None = None,
    priority: str | None = None,
    status_note_public: bool = False,
) -> dict[str, Any]:
    """Atualiza um ticket no HubSpot e opcionalmente anexa uma nota de resposta.

    Esta é a ferramenta de FECHAMENTO DE LOOP do HelpdeskActionAgent: depois
    da triagem o agente DEVE chamar esta função para mover o ticket para o
    próximo estágio do pipeline e registrar a resposta preparada.

    Args:
        ticket_id: ID numérico do ticket no HubSpot.
        pipeline_stage: Novo `hs_pipeline_stage` (ex.: "2" = open,
            "3" = waiting, "4" = closed). Deixe None para preservar.
        reply_note: Texto da resposta/nota a anexar ao ticket. Quando
            informado, cria uma Note via Engagements API e a associa ao
            ticket. Evite colocar tokens ou dados sensíveis.
        priority: Novo `hs_ticket_priority` (LOW, MEDIUM, HIGH, URGENT).
            None preserva o valor atual.
        status_note_public: Quando True, sinaliza (via metadata.public) que
            a nota pode ser exibida ao contato. Default False (interna).

    Returns:
        Dict com campos:
            - ticket_id: str
            - stage_updated: bool
            - priority_updated: bool
            - note_created: bool
            - note_id: str | None
            - errors: list[str] (vazia quando tudo ok)
    """
    headers = _build_headers()
    errors: list[str] = []
    note_id: str | None = None

    props: dict[str, str] = {}
    if pipeline_stage is not None:
        props["hs_pipeline_stage"] = pipeline_stage
    if priority is not None:
        props["hs_ticket_priority"] = priority

    stage_updated = False
    priority_updated = False
    note_created = False

    logger.info(
        "hubspot_update_ticket_start",
        ticket_id=ticket_id,
        stage=pipeline_stage,
        priority=priority,
        has_note=bool(reply_note),
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1) PATCH no ticket — propriedades (stage/priority)
        if props:
            try:
                response = await client.patch(
                    f"{HUBSPOT_API_BASE}/crm/v3/objects/tickets/{ticket_id}",
                    headers=headers,
                    json={"properties": props},
                )
                response.raise_for_status()
                stage_updated = "hs_pipeline_stage" in props
                priority_updated = "hs_ticket_priority" in props
            except httpx.HTTPStatusError as exc:
                errors.append(f"patch_ticket:{exc.response.status_code}")
                logger.error(
                    "hubspot_update_ticket_patch_failed",
                    ticket_id=ticket_id,
                    status_code=exc.response.status_code,
                    body=exc.response.text[:200],
                )
            except httpx.HTTPError as exc:
                errors.append(f"patch_ticket:{exc.__class__.__name__}")
                logger.error("hubspot_update_ticket_patch_error", ticket_id=ticket_id, error=str(exc))

        # 2) Cria uma Note e associa ao ticket (engagements v3)
        if reply_note:
            import time as _time

            note_payload: dict[str, Any] = {
                "properties": {
                    "hs_timestamp": int(_time.time() * 1000),
                    "hs_note_body": reply_note,
                    "hubspot_owner_id": "",
                },
                "associations": [
                    {
                        "to": {"id": ticket_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                # Note → Ticket (association type id 228)
                                "associationTypeId": 228,
                            }
                        ],
                    }
                ],
            }
            if status_note_public:
                note_payload["properties"]["hs_note_body_public"] = "true"

            try:
                response = await client.post(
                    f"{HUBSPOT_API_BASE}/crm/v3/objects/notes",
                    headers=headers,
                    json=note_payload,
                )
                response.raise_for_status()
                note_id = response.json().get("id")
                note_created = note_id is not None
            except httpx.HTTPStatusError as exc:
                errors.append(f"create_note:{exc.response.status_code}")
                logger.error(
                    "hubspot_update_ticket_note_failed",
                    ticket_id=ticket_id,
                    status_code=exc.response.status_code,
                    body=exc.response.text[:200],
                )
            except httpx.HTTPError as exc:
                errors.append(f"create_note:{exc.__class__.__name__}")
                logger.error("hubspot_update_ticket_note_error", ticket_id=ticket_id, error=str(exc))

    logger.info(
        "hubspot_update_ticket_done",
        ticket_id=ticket_id,
        stage_updated=stage_updated,
        priority_updated=priority_updated,
        note_created=note_created,
        errors=errors or None,
    )

    return {
        "ticket_id": ticket_id,
        "stage_updated": stage_updated,
        "priority_updated": priority_updated,
        "note_created": note_created,
        "note_id": note_id,
        "errors": errors,
    }


async def _resolve_contact_by_email(email: str) -> str | None:
    """Resolve um email para ID de contato HubSpot.

    Args:
        email: Email do contato.

    Returns:
        ID do contato ou None se não encontrado.
    """
    url = f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/search"
    headers = _build_headers()

    payload = {
        "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
        "properties": ["email"],
        "limit": 1,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if results:
                return results[0].get("id")
            return None

        except Exception as exc:
            logger.warning("hubspot_resolve_contact_failed", email=email, error=str(exc))
            return None


def _get_portal_id() -> str:
    """Recupera o portal ID via variável de ambiente.

    Returns:
        Portal ID do HubSpot ou string vazia.
    """
    return os.getenv("HUBSPOT_PORTAL_ID", "")


def _map_stage_to_status(stage: str) -> str:
    """Mapeia stage numérico para status legível.

    Args:
        stage: ID do stage do pipeline.

    Returns:
        Status legível (new, open, waiting, closed).
    """
    stage_map = {
        "1": "new",
        "939275049": "new",
        "2": "open",
        "3": "waiting",
        "4": "closed",
        "939275052": "closed",
    }
    return stage_map.get(stage, "unknown")


if __name__ == "__main__":
    # Modo stdio: comunicação via stdin/stdout para subprocesso
    # O Agno MCP client irá gerenciar este processo
    mcp.run(transport="stdio")
