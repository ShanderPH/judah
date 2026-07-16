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

import asyncio
import base64
import json
import os
import re
from typing import Any, Literal, cast
from urllib.parse import urlparse

import httpx
import structlog
from django.conf import settings

from apps.ai_agents.contracts import ConversationContext, ConversationMessage
from apps.ai_agents.services.channel_capabilities import can_send_automated_reply

logger = structlog.get_logger(__name__)

HUBSPOT_API_BASE = "https://api.hubapi.com"
ConversationChannel = Literal["hubspot", "webchat_central", "api"]
SUPPORTED_IMAGE_MIME_TYPES = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})
DEFAULT_IMAGE_MAX_BYTES = 8 * 1024 * 1024

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
                "attachments": raw.get("attachments") or [],
                "raw": raw,
            }
        )
    return messages


def _image_mime_type(content: bytes) -> str | None:
    """Detect the image formats accepted by Salomao v1 from file signatures."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _looks_like_image_attachment(attachment: dict[str, Any]) -> bool:
    mime_type = str(attachment.get("mimeType") or attachment.get("contentType") or "").lower()
    usage_type = str(attachment.get("fileUsageType") or "").upper()
    name = str(attachment.get("name") or attachment.get("url") or "").lower().split("?", 1)[0]
    return (
        mime_type in SUPPORTED_IMAGE_MIME_TYPES
        or usage_type in {"IMAGE", "STICKER"}
        or name.endswith((".gif", ".jpeg", ".jpg", ".png", ".webp"))
    )


def _latest_incoming_image_attachment(context: dict[str, Any]) -> dict[str, Any] | None:
    latest = _latest_incoming_message(context)
    if not latest:
        return None
    return _latest_image_attachment_in_message(latest)


def _latest_image_attachment_in_message(message: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            attachment
            for attachment in message.get("attachments") or []
            if isinstance(attachment, dict)
            and str(attachment.get("type") or "FILE").upper() == "FILE"
            and _looks_like_image_attachment(attachment)
        ),
        None,
    )


async def _resolve_attachment_url(client: httpx.AsyncClient, attachment: dict[str, Any]) -> str | None:
    if attachment.get("url"):
        return str(attachment["url"])

    file_id = attachment.get("fileId")
    if not file_id:
        return None
    response = await client.get(f"{HUBSPOT_API_BASE}/files/v3/files/{file_id}/signed-url")
    response.raise_for_status()
    return response.json().get("url")


def _is_allowed_attachment_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname:
        return False
    if hostname in {"hubapi.com", "hubspot.com"} or hostname.endswith((".hubapi.com", ".hubspot.com")):
        return True
    return any(label.startswith("hubspotusercontent") for label in hostname.split("."))


async def _download_image_attachment(
    client: httpx.AsyncClient,
    attachment: dict[str, Any],
    *,
    max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
) -> tuple[str, str]:
    url = await _resolve_attachment_url(client, attachment)
    if not url or not _is_allowed_attachment_url(url):
        raise ValueError("HubSpot attachment URL is missing or is not trusted.")

    content = bytearray()
    async with client.stream("GET", url, headers={"Authorization": ""}) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("HubSpot image attachment exceeds the configured size limit.")
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > max_bytes:
                raise ValueError("HubSpot image attachment exceeds the configured size limit.")

    mime_type = _image_mime_type(bytes(content))
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError("HubSpot attachment is not a supported image.")
    return base64.b64encode(content).decode("ascii"), mime_type


async def _hydrate_latest_incoming_image(client: httpx.AsyncClient, context: dict[str, Any]) -> None:
    attachment = _latest_incoming_image_attachment(context)
    if not attachment:
        return

    try:
        max_bytes = int(os.getenv("HUBSPOT_IMAGE_MAX_BYTES", str(DEFAULT_IMAGE_MAX_BYTES)))
        image_base64, image_mime_type = await _download_image_attachment(
            client,
            attachment,
            max_bytes=max_bytes,
        )
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        logger.warning(
            "hubspot_image_attachment_ignored",
            message_id=(_latest_incoming_message(context) or {}).get("id"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        context.setdefault("errors", []).append(f"image_attachment:{type(exc).__name__}")
        return

    context["image_base64"] = image_base64
    context["image_mime_type"] = image_mime_type
    context["image_name"] = attachment.get("name") or None
    logger.info(
        "hubspot_image_attachment_hydrated",
        message_id=(_latest_incoming_message(context) or {}).get("id"),
        mime_type=image_mime_type,
        size_bytes=len(base64.b64decode(image_base64)),
    )


async def _fetch_thread(client: httpx.AsyncClient, thread_id: str) -> dict[str, Any]:
    response = await client.get(f"{HUBSPOT_API_BASE}/conversations/v3/conversations/threads/{thread_id}")
    response.raise_for_status()
    return response.json()


def _parse_restored_thread_ids(value: Any) -> list[str]:
    """Parse HubSpot's thread restore property into stable thread IDs."""
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not value:
        return []

    text = str(value).strip()
    try:
        decoded = json.loads(text)
    except TypeError, ValueError:
        decoded = None
    if isinstance(decoded, list):
        return [str(item) for item in decoded if str(item).strip()]

    return re.findall(r"\d+", text)


def _extract_thread_ids(ticket_payload: dict[str, Any]) -> list[str]:
    """Extract associated threads, with the ticket restore property as fallback."""
    associations = ticket_payload.get("associations") or {}
    conv = associations.get("conversations") or {}
    results = conv.get("results") or []
    association_ids = [str(item.get("id")) for item in results if item.get("id")]
    properties = ticket_payload.get("properties") or {}
    restored_ids = _parse_restored_thread_ids(properties.get("hs_thread_ids_to_restore"))
    return list(dict.fromkeys([*association_ids, *restored_ids]))


async def update_hubspot_ticket_stage(
    ticket_id: str,
    stage_id: str,
    *,
    timeout_seconds: float = 20.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Move a HubSpot ticket to a stage, retrying transient provider failures."""
    return await update_hubspot_ticket_route(
        ticket_id,
        stage_id,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


async def update_hubspot_ticket_route(
    ticket_id: str,
    stage_id: str,
    *,
    pipeline_id: str | None = None,
    timeout_seconds: float = 20.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Move a ticket to a stage and, when provided, to another pipeline."""
    if USE_MOCK_HUBSPOT:
        return {
            "updated": True,
            "ticket_id": str(ticket_id),
            **({"pipeline_id": str(pipeline_id)} if pipeline_id else {}),
            "stage_id": str(stage_id),
            "attempts": 1,
        }

    properties = {"hs_pipeline_stage": str(stage_id)}
    if pipeline_id:
        properties["hs_pipeline"] = str(pipeline_id)
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(headers=_auth_headers(), timeout=timeout) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.patch(
                    f"{HUBSPOT_API_BASE}/crm/v3/objects/tickets/{ticket_id}",
                    json={"properties": properties},
                )
                if (response.status_code == 429 or response.status_code >= 500) and attempt < max_attempts:
                    await asyncio.sleep(0.25 * attempt)
                    continue
                response.raise_for_status()
                logger.info(
                    "hubspot_ticket_stage_updated",
                    ticket_id=ticket_id,
                    pipeline_id=pipeline_id,
                    stage_id=stage_id,
                    attempts=attempt,
                )
                return {
                    "updated": True,
                    "ticket_id": str(ticket_id),
                    **({"pipeline_id": str(pipeline_id)} if pipeline_id else {}),
                    "stage_id": str(stage_id),
                    "attempts": attempt,
                }
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "hubspot_ticket_stage_update_http_error",
                    ticket_id=ticket_id,
                    pipeline_id=pipeline_id,
                    stage_id=stage_id,
                    status=exc.response.status_code,
                    attempts=attempt,
                )
                return {
                    "updated": False,
                    "ticket_id": str(ticket_id),
                    **({"pipeline_id": str(pipeline_id)} if pipeline_id else {}),
                    "stage_id": str(stage_id),
                    "attempts": attempt,
                    "reason": f"http:{exc.response.status_code}",
                }
            except httpx.HTTPError as exc:
                if attempt < max_attempts:
                    await asyncio.sleep(0.25 * attempt)
                    continue
                logger.error(
                    "hubspot_ticket_stage_update_error",
                    ticket_id=ticket_id,
                    pipeline_id=pipeline_id,
                    stage_id=stage_id,
                    error_type=type(exc).__name__,
                    attempts=attempt,
                )
                return {
                    "updated": False,
                    "ticket_id": str(ticket_id),
                    **({"pipeline_id": str(pipeline_id)} if pipeline_id else {}),
                    "stage_id": str(stage_id),
                    "attempts": attempt,
                    "reason": type(exc).__name__,
                }

    return {
        "updated": False,
        "ticket_id": str(ticket_id),
        **({"pipeline_id": str(pipeline_id)} if pipeline_id else {}),
        "stage_id": str(stage_id),
        "attempts": max_attempts,
        "reason": "unknown",
    }


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

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
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
        await _hydrate_latest_incoming_image(client, context)

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

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        try:
            thread = await _fetch_thread(client, thread_id)
            context["threads"].append(thread)
            context["ticket_id"] = str((thread.get("threadAssociations") or {}).get("associatedTicketId") or "")
            contact_id = thread.get("associatedContactId")
            context["contact_ids"] = [str(contact_id)] if contact_id else []
            context["originating_channel"] = thread.get("originalChannelId") or ""
            context["conversation_history"] = await _fetch_conversation_history(client, thread_id, limit=limit)
            await _hydrate_latest_incoming_image(client, context)
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
        if (message.get("direction") or "").upper() == "INCOMING"
        and (
            (message.get("text") or "").strip()
            or any(_looks_like_image_attachment(a) for a in message.get("attachments") or [] if isinstance(a, dict))
        )
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
        f"Mensagem atual do cliente:\n{latest.get('text') or '[Imagem enviada pelo cliente]'}"
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
            text=(message.get("text") or "").strip()
            or ("[Imagem enviada pelo cliente]" if _latest_image_attachment_in_message(message) else ""),
            created_at=message.get("created_at"),
            actor_id=message.get("sender"),
            message_id=str(message.get("id")) if message.get("id") else None,
        )
        for message in history
        if (message.get("text") or "").strip() or _latest_image_attachment_in_message(message)
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
    configured_sender_actor_id = str(
        os.getenv("HUBSPOT_SALOMAO_SENDER_ACTOR_ID") or getattr(settings, "HUBSPOT_SALOMAO_SENDER_ACTOR_ID", "") or ""
    ).strip()
    incoming_recipients = latest.get("recipients") or []
    fallback_sender_actor_id = next(
        (str(recipient.get("actorId")) for recipient in incoming_recipients if recipient.get("actorId")),
        "",
    )
    sender_actor_id = configured_sender_actor_id or fallback_sender_actor_id
    if sender_actor_id and not configured_sender_actor_id:
        logger.info("hubspot_salomao_sender_actor_inferred", thread_id=thread_id)
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
    "update_hubspot_ticket_route",
    "update_hubspot_ticket_stage",
]
