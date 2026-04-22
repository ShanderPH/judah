"""Serviço de hidratação de contexto HubSpot para o pipeline Salomão.

Quando o webhook do HubSpot dispara, ele entrega apenas `objectId` (ticket_id)
e o delta da propriedade alterada. Este módulo expande esse payload mínimo
para o dicionário que o `SalomaoSupervisorAgent` consome — espelhando os
nós `Get Full Ticket Data` e `Get Conversation History` do fluxo N8N.

Decisões:
- `httpx.AsyncClient` com HTTP/2 desabilitado (compat) e `follow_redirects=True`.
- Token vindo apenas de `os.getenv("HUBSPOT_ACCESS_TOKEN")`, sem Django ORM,
  mantendo o módulo utilizável em background tasks e workers sem app-ready.
- Qualquer falha de rede é logada e convertida em dicionário-erro parcial
  para que o pipeline possa seguir com o que tiver, em vez de abortar.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

HUBSPOT_API_BASE = "https://api.hubapi.com"

# QA/dev switch: quando True, `hydrate_ticket_context` devolve um payload
# sintético sem tocar na API do HubSpot. Usado pelo simulador local de
# webhooks (scripts/simulate_hubspot_webhook.py) para validar o pipeline
# assíncrono sem precisar de Ngrok/tokens reais.
USE_MOCK_HUBSPOT = os.getenv("USE_MOCK_HUBSPOT", "False") == "True"


def _mock_ticket_context(ticket_id: str) -> dict[str, Any]:
    """Payload de mentira no mesmo shape que a HubSpot API retornaria.

    Serve apenas para o modo `USE_MOCK_HUBSPOT=True`. Imita o caso clássico
    de um membro pedindo 2ª via de boleto — deve rotear para o agente BOLETO
    na triagem do Salomão.
    """
    return {
        "ticket_id": ticket_id,
        "subject": "Erro ao emitir boleto",
        "content": "Não consigo gerar a segunda via do boleto deste mês.",
        "owner_id": "mock-owner-001",
        "originating_channel": "CHAT",
        "pipeline": "0",
        "pipeline_stage": "1",
        "priority": "high",
        "contact_ids": ["mock-contact-001"],
        "conversation_history": [
            {
                "id": "mock-msg-001",
                "sender": "mock-contact-001",
                "direction": "INCOMING",
                "text": "Preciso de ajuda urgente para emitir meu boleto.",
                "created_at": "2026-04-20T12:00:00Z",
            },
        ],
        "raw_ticket": {"mock": True},
        "errors": [],
    }


# Propriedades essenciais que o Supervisor usa como contexto da triagem.
_TICKET_PROPERTIES: list[str] = [
    "subject",
    "content",
    "hs_ticket_priority",
    "hs_pipeline",
    "hs_pipeline_stage",
    "hubspot_owner_id",
    "source_type",  # Originating Channel (chat, email, form, etc.)
    "hs_last_message_from_visitor",
    "hs_thread_ids_to_restore",
    "createdate",
    "hs_lastmodifieddate",
]


def _auth_headers() -> dict[str, str]:
    """Monta o header Authorization; erro explícito se o token estiver ausente."""
    token = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("HUBSPOT_ACCESS_TOKEN não configurado — hidratação de ticket inviável.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _fetch_ticket(client: httpx.AsyncClient, ticket_id: str) -> dict[str, Any]:
    """Busca o ticket + propriedades essenciais + associações (contato/conversa)."""
    params = {
        "properties": ",".join(_TICKET_PROPERTIES),
        "associations": "contacts,conversations",
        "archived": "false",
    }
    response = await client.get(
        f"{HUBSPOT_API_BASE}/crm/v3/objects/tickets/{ticket_id}",
        params=params,
    )
    response.raise_for_status()
    return response.json()


async def _fetch_conversation_history(
    client: httpx.AsyncClient,
    thread_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Busca mensagens recentes de uma thread da Conversations API.

    Retorna lista enxuta (role + texto + timestamp) para não estourar o
    contexto do LLM. Se a thread não existir mais, retorna lista vazia.
    """
    try:
        response = await client.get(
            f"{HUBSPOT_API_BASE}/conversations/v3/conversations/threads/{thread_id}/messages",
            params={"limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "hubspot_thread_fetch_failed",
            thread_id=thread_id,
            status=exc.response.status_code,
        )
        return []

    messages: list[dict[str, Any]] = []
    for raw in payload.get("results", []):
        messages.append(
            {
                "id": raw.get("id"),
                "sender": (raw.get("senders") or [{}])[0].get("actorId", "unknown"),
                "direction": raw.get("direction", "UNKNOWN"),
                "text": (raw.get("text") or "").strip(),
                "created_at": raw.get("createdAt"),
            }
        )
    return messages


def _extract_thread_ids(ticket_payload: dict[str, Any]) -> list[str]:
    """Extrai IDs de thread de conversa associados ao ticket."""
    associations = ticket_payload.get("associations") or {}
    conv = associations.get("conversations") or {}
    results = conv.get("results") or []
    return [str(item.get("id")) for item in results if item.get("id")]


async def hydrate_ticket_context(
    ticket_id: str,
    *,
    timeout_seconds: float = 20.0,
    max_threads: int = 2,
) -> dict[str, Any]:
    """Expande o payload mínimo do webhook no contexto completo do ticket.

    Equivale aos nós 'Get Full Ticket Data' + 'Get Conversation History' do
    N8N. Estrutura de retorno estável para consumo do `SalomaoSupervisorAgent`:

        {
            "ticket_id": str,
            "subject": str,
            "content": str,
            "owner_id": str,
            "originating_channel": str,
            "pipeline": str,
            "pipeline_stage": str,
            "priority": str,
            "contact_ids": list[str],
            "conversation_history": list[dict],   # normalizado
            "raw_ticket": dict,                   # payload bruto para debug
            "errors": list[str],                  # falhas parciais não-fatais
        }

    Args:
        ticket_id: ID do ticket recebido no webhook (`objectId`).
        timeout_seconds: Timeout por request HTTP.
        max_threads: Número máximo de threads a hidratar (limita tokens).
    """
    if USE_MOCK_HUBSPOT:
        logger.info("hubspot_context_mocked", ticket_id=ticket_id)
        return _mock_ticket_context(ticket_id)

    errors: list[str] = []
    context: dict[str, Any] = {
        "ticket_id": ticket_id,
        "subject": "",
        "content": "",
        "owner_id": "",
        "originating_channel": "",
        "pipeline": "",
        "pipeline_stage": "",
        "priority": "",
        "contact_ids": [],
        "conversation_history": [],
        "raw_ticket": {},
        "errors": errors,
    }

    headers = _auth_headers()
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        try:
            ticket = await _fetch_ticket(client, ticket_id)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "hubspot_ticket_fetch_failed",
                ticket_id=ticket_id,
                status=exc.response.status_code,
            )
            errors.append(f"ticket_fetch:{exc.response.status_code}")
            return context
        except httpx.HTTPError as exc:
            logger.error("hubspot_ticket_fetch_error", ticket_id=ticket_id, error=str(exc))
            errors.append(f"ticket_fetch:{exc.__class__.__name__}")
            return context

        props = ticket.get("properties", {}) or {}
        context["subject"] = props.get("subject", "") or ""
        context["content"] = props.get("content", "") or ""
        context["owner_id"] = props.get("hubspot_owner_id", "") or ""
        context["originating_channel"] = props.get("source_type", "") or ""
        context["pipeline"] = props.get("hs_pipeline", "") or ""
        context["pipeline_stage"] = props.get("hs_pipeline_stage", "") or ""
        context["priority"] = props.get("hs_ticket_priority", "") or ""
        context["raw_ticket"] = ticket

        associations = ticket.get("associations") or {}
        contacts = (associations.get("contacts") or {}).get("results") or []
        context["contact_ids"] = [str(c.get("id")) for c in contacts if c.get("id")]

        thread_ids = _extract_thread_ids(ticket)[:max_threads]
        history: list[dict[str, Any]] = []
        for thread_id in thread_ids:
            try:
                history.extend(await _fetch_conversation_history(client, thread_id))
            except httpx.HTTPError as exc:
                logger.warning(
                    "hubspot_history_fetch_error",
                    thread_id=thread_id,
                    error=str(exc),
                )
                errors.append(f"history:{thread_id}")

        context["conversation_history"] = sorted(
            history,
            key=lambda m: m.get("created_at") or "",
        )

    logger.info(
        "hubspot_context_hydrated",
        ticket_id=ticket_id,
        history_count=len(context["conversation_history"]),
        owner_id=context["owner_id"] or None,
        errors=errors or None,
    )
    return context


__all__ = ["hydrate_ticket_context"]
