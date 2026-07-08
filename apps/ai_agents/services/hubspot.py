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
from typing import Any, Literal, cast

import httpx
import structlog

from apps.ai_agents.contracts import ConversationContext, ConversationMessage
from apps.ai_agents.services.channel_capabilities import can_send_automated_reply

logger = structlog.get_logger(__name__)

HUBSPOT_API_BASE = "https://api.hubapi.com"
ConversationChannel = Literal["hubspot", "webchat_central", "api"]

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
        "thread_ids": ["mock-thread-001"],
        "conversation_history": [
            {
                "id": "mock-msg-001",
                "thread_id": "mock-thread-001",
                "sender": "mock-contact-001",
                "direction": "INCOMING",
                "text": "Preciso de ajuda urgente para emitir meu boleto.",
                "created_at": "2026-04-20T12:00:00Z",
                "channel_id": "mock-channel",
                "channel_account_id": "mock-channel-account",
                "senders": [{"actorId": "V-mock-contact-001", "name": "Cliente"}],
                "recipients": [{"actorId": "A-mock-agent", "name": "Suporte"}],
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
        senders = raw.get("senders") or []
        recipients = raw.get("recipients") or []
        messages.append(
            {
                "id": raw.get("id"),
                "thread_id": str(raw.get("conversationsThreadId") or thread_id),
                "sender": (senders or [{}])[0].get("actorId", "unknown"),
                "direction": raw.get("direction", "UNKNOWN"),
                "text": (raw.get("text") or "").strip(),
                "created_at": raw.get("createdAt"),
                "channel_id": raw.get("channelId"),
                "channel_account_id": raw.get("channelAccountId"),
                "senders": senders,
                "recipients": recipients,
                "raw": raw,
            }
        )
    return messages


async def _fetch_thread(client: httpx.AsyncClient, thread_id: str) -> dict[str, Any]:
    response = await client.get(f"{HUBSPOT_API_BASE}/conversations/v3/conversations/threads/{thread_id}")
    response.raise_for_status()
    return response.json()


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
        "thread_ids": [],
        "threads": [],
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
        context["thread_ids"] = thread_ids
        history: list[dict[str, Any]] = []
        for thread_id in thread_ids:
            try:
                context["threads"].append(await _fetch_thread(client, thread_id))
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


async def hydrate_thread_context(
    thread_id: str,
    *,
    timeout_seconds: float = 20.0,
    limit: int = 20,
) -> dict[str, Any]:
    """Hydrate a single HubSpot conversation thread for Salomao v1 routing."""
    if USE_MOCK_HUBSPOT:
        context = _mock_ticket_context(f"mock-ticket-for-thread-{thread_id}")
        context["thread_ids"] = [thread_id]
        for message in context["conversation_history"]:
            message["thread_id"] = thread_id
        return context

    headers = _auth_headers()
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    errors: list[str] = []
    context: dict[str, Any] = {
        "ticket_id": "",
        "subject": "",
        "content": "",
        "owner_id": "",
        "originating_channel": "",
        "pipeline": "",
        "pipeline_stage": "",
        "priority": "",
        "contact_ids": [],
        "thread_ids": [str(thread_id)],
        "threads": [],
        "conversation_history": [],
        "raw_ticket": {},
        "errors": errors,
    }

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        try:
            thread = await _fetch_thread(client, thread_id)
            context["threads"].append(thread)
            context["ticket_id"] = str((thread.get("threadAssociations") or {}).get("associatedTicketId") or "")
            contact_id = thread.get("associatedContactId")
            context["contact_ids"] = [str(contact_id)] if contact_id else []
            context["originating_channel"] = thread.get("originalChannelId") or ""
            context["conversation_history"] = await _fetch_conversation_history(client, thread_id, limit=limit)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "hubspot_thread_context_fetch_failed",
                thread_id=thread_id,
                status=exc.response.status_code,
            )
            errors.append(f"thread_fetch:{exc.response.status_code}")
        except httpx.HTTPError as exc:
            logger.error("hubspot_thread_context_fetch_error", thread_id=thread_id, error=str(exc))
            errors.append(f"thread_fetch:{exc.__class__.__name__}")

    logger.info(
        "hubspot_thread_context_hydrated",
        thread_id=thread_id,
        ticket_id=context["ticket_id"] or None,
        history_count=len(context["conversation_history"]),
        errors=errors or None,
    )
    return context


def _latest_incoming_message(context: dict[str, Any]) -> dict[str, Any] | None:
    history = context.get("conversation_history") or []
    incoming = [
        message
        for message in history
        if (message.get("direction") or "").upper() == "INCOMING" and (message.get("text") or "").strip()
    ]
    return incoming[-1] if incoming else None


def build_salomao_prompt_from_hubspot_context(context: dict[str, Any]) -> str | None:
    """Build the text Judah sends to Salomao v1 from HubSpot chat context."""
    latest = _latest_incoming_message(context)
    if not latest:
        return None

    history_lines = [
        f"[{message.get('direction')}] {message.get('text')}"
        for message in context.get("conversation_history", [])
        if message.get("text")
    ]
    history_block = "\n".join(history_lines[-12:])
    ticket_id = context.get("ticket_id") or "(sem ticket associado)"
    subject = context.get("subject") or "(sem assunto)"

    return (
        f"Atendimento HubSpot\n"
        f"Ticket: {ticket_id}\n"
        f"Assunto: {subject}\n\n"
        f"Historico recente:\n{history_block}\n\n"
        f"Mensagem atual do cliente:\n{latest['text']}"
    )


def build_conversation_context_from_hubspot_context(
    context: dict[str, Any],
    *,
    channel: str = "hubspot",
    session_id: str,
    is_off_hours: bool = False,
) -> ConversationContext:
    """Normalize hydrated HubSpot context into the internal ConversationContext contract."""
    history = context.get("conversation_history") or []
    messages = [
        ConversationMessage(
            direction=(message.get("direction") or "UNKNOWN").upper()
            if (message.get("direction") or "").upper() in {"INCOMING", "OUTGOING", "UNKNOWN"}
            else "UNKNOWN",
            text=(message.get("text") or "").strip(),
            created_at=message.get("created_at"),
            actor_id=message.get("sender"),
            message_id=str(message.get("id")) if message.get("id") else None,
        )
        for message in history
        if (message.get("text") or "").strip()
    ]

    thread_ids = context.get("thread_ids") or []
    contact_ids = context.get("contact_ids") or []
    raw_channel = context.get("originating_channel") or context.get("channel") or channel
    can_send_reply = can_send_automated_reply(str(raw_channel))
    allowed_actions = ["mark_ai_resolution_attempt"]
    if thread_ids and can_send_reply:
        allowed_actions.append("send_thread_reply")
    if context.get("ticket_id"):
        allowed_actions.extend(["update_ticket_stage", "assign_ticket_to_human_queue", "add_internal_note"])

    missing_context: list[str] = []
    if not context.get("ticket_id"):
        missing_context.append("ticket_id")
    if not thread_ids:
        missing_context.append("thread_id")
    if not messages:
        missing_context.append("recent_messages")

    return ConversationContext(
        channel=cast("ConversationChannel", channel),
        session_id=session_id,
        ticket_id=context.get("ticket_id") or None,
        thread_id=str(thread_ids[0]) if thread_ids else None,
        contact_id=str(contact_ids[0]) if contact_ids else None,
        pipeline_id=context.get("pipeline") or None,
        pipeline_stage=context.get("pipeline_stage") or None,
        owner_id=context.get("owner_id") or None,
        is_off_hours=is_off_hours,
        can_send_reply=can_send_reply,
        recent_messages=messages[-20:],
        allowed_actions=allowed_actions,
        missing_context=missing_context,
    )


def _recipient_from_sender(sender: dict[str, Any]) -> dict[str, Any]:
    recipient: dict[str, Any] = {}
    if sender.get("actorId"):
        recipient["actorId"] = sender["actorId"]
    if sender.get("name"):
        recipient["name"] = sender["name"]
    if sender.get("recipientField"):
        recipient["recipientField"] = sender["recipientField"]

    delivery_identifiers = sender.get("deliveryIdentifiers")
    if not delivery_identifiers and sender.get("deliveryIdentifier"):
        delivery_identifiers = [sender["deliveryIdentifier"]]
    if delivery_identifiers:
        recipient["deliveryIdentifiers"] = delivery_identifiers

    return recipient


async def send_salomao_reply_to_hubspot_thread(
    context: dict[str, Any],
    text: str,
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Post Salomao's answer back to the HubSpot conversation thread."""
    latest = _latest_incoming_message(context)
    if not latest:
        return {"sent": False, "reason": "no_incoming_message"}

    thread_id = latest.get("thread_id")
    channel_id = latest.get("channel_id")
    channel_account_id = latest.get("channel_account_id")
    sender_actor_id = os.getenv("HUBSPOT_SALOMAO_SENDER_ACTOR_ID", "")
    recipients = [_recipient_from_sender(sender) for sender in latest.get("senders", [])]
    recipients = [recipient for recipient in recipients if recipient]

    missing = [
        name
        for name, value in {
            "thread_id": thread_id,
            "channel_id": channel_id,
            "channel_account_id": channel_account_id,
            "sender_actor_id": sender_actor_id,
            "recipients": recipients,
        }.items()
        if not value
    ]
    if missing:
        logger.error(
            "hubspot_salomao_reply_missing_fields",
            thread_id=thread_id,
            missing=missing,
        )
        return {"sent": False, "reason": "missing_fields", "missing": missing}

    headers = _auth_headers()
    payload = {
        "attachments": [],
        "channelAccountId": channel_account_id,
        "channelId": channel_id,
        "recipients": recipients,
        "senderActorId": sender_actor_id,
        "text": text,
        "type": "MESSAGE",
        "richText": text,
    }

    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        try:
            response = await client.post(
                f"{HUBSPOT_API_BASE}/conversations/v3/conversations/threads/{thread_id}/messages",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "hubspot_salomao_reply_sent",
                thread_id=thread_id,
                message_id=data.get("id"),
            )
            return {"sent": True, "thread_id": thread_id, "message_id": data.get("id"), "raw": data}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "hubspot_salomao_reply_http_error",
                thread_id=thread_id,
                status=exc.response.status_code,
                body=exc.response.text[:300],
            )
            return {"sent": False, "reason": f"http:{exc.response.status_code}"}
        except httpx.HTTPError as exc:
            logger.error("hubspot_salomao_reply_error", thread_id=thread_id, error=str(exc))
            return {"sent": False, "reason": exc.__class__.__name__}


__all__ = [
    "build_conversation_context_from_hubspot_context",
    "build_salomao_prompt_from_hubspot_context",
    "hydrate_thread_context",
    "hydrate_ticket_context",
    "send_salomao_reply_to_hubspot_thread",
]
