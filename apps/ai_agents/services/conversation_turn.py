"""Helpers for treating consecutive customer messages as one logical turn."""

from __future__ import annotations

import hashlib
import json
from typing import Any

IMAGE_PLACEHOLDER = "[Imagem enviada pelo cliente]"
CURRENT_CUSTOMER_TURN_MARKER = "Turno atual do cliente (mensagens consecutivas, em ordem):"
LEGACY_CUSTOMER_MESSAGE_MARKER = "Mensagem atual do cliente:"


def _has_content(message: dict[str, Any]) -> bool:
    return bool(str(message.get("text") or "").strip() or message.get("attachments"))


def current_incoming_turn(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return consecutive incoming messages since the latest outgoing reply.

    HubSpot history is the durable source of truth. System/unknown events are
    ignored, while an outgoing message closes the previous customer turn.
    """
    history = [message for message in context.get("conversation_history") or [] if _has_content(message)]
    if not history or str(history[-1].get("direction") or "").upper() != "INCOMING":
        return []

    reversed_turn: list[dict[str, Any]] = []
    for message in reversed(history):
        direction = str(message.get("direction") or "").upper()
        if direction == "OUTGOING":
            break
        if direction == "INCOMING":
            reversed_turn.append(message)
    return list(reversed(reversed_turn))


def incoming_message_id(message: dict[str, Any]) -> str:
    """Return a stable provider ID or privacy-safe fingerprint for a message."""
    if message.get("id"):
        return str(message["id"])
    fingerprint = {
        "thread_id": message.get("thread_id"),
        "created_at": message.get("created_at"),
        "sender": message.get("sender"),
        "text": message.get("text"),
        "attachments": message.get("attachments") or [],
    }
    serialized = json.dumps(fingerprint, sort_keys=True, default=str, ensure_ascii=False)
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def latest_incoming_message_id(context: dict[str, Any]) -> str:
    """Return the identity of the most recent incoming message, if present."""
    for message in reversed(context.get("conversation_history") or []):
        if str(message.get("direction") or "").upper() == "INCOMING":
            return incoming_message_id(message)
    return ""


def current_incoming_turn_text(context: dict[str, Any]) -> str:
    """Render the current customer turn in chronological order for agents."""
    parts: list[str] = []
    for message in current_incoming_turn(context):
        text = str(message.get("text") or "").strip()
        parts.append(text or IMAGE_PLACEHOLDER)
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return "\n".join(f"{index}. {text}" for index, text in enumerate(parts, start=1))


def current_incoming_turn_audit(context: dict[str, Any]) -> dict[str, Any] | None:
    """Build a PII-free audit summary for the current grouped customer turn."""
    messages = current_incoming_turn(context)
    if not messages:
        return None
    message_ids = [incoming_message_id(message) for message in messages]
    return {
        "message_count": len(messages),
        "message_ids": message_ids,
        "first_message_id": message_ids[0],
        "last_message_id": message_ids[-1],
        "first_created_at": messages[0].get("created_at"),
        "last_created_at": messages[-1].get("created_at"),
    }


def extract_current_customer_turn(message: str) -> str:
    """Extract the current turn from current and legacy HubSpot envelopes."""
    for marker in (CURRENT_CUSTOMER_TURN_MARKER, LEGACY_CUSTOMER_MESSAGE_MARKER):
        if marker in message:
            return message.rsplit(marker, maxsplit=1)[-1].strip()
    return message.strip()


__all__ = [
    "CURRENT_CUSTOMER_TURN_MARKER",
    "IMAGE_PLACEHOLDER",
    "current_incoming_turn",
    "current_incoming_turn_audit",
    "current_incoming_turn_text",
    "extract_current_customer_turn",
    "incoming_message_id",
    "latest_incoming_message_id",
]
