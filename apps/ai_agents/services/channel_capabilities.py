"""Deterministic channel capability checks for AI/helpdesk routing."""

from __future__ import annotations

from django.conf import settings


def normalize_channel(value: str | None) -> str:
    """Return a normalized channel key used by routing policies."""
    channel = (value or "").strip().lower()
    if not channel:
        return "unknown"
    if "whatsapp" in channel or channel in {"wa", "waba"}:
        return "whatsapp"
    if channel in {"chat", "webchat", "webchat_central", "live_chat"}:
        return "chat"
    if channel in {"email", "mail"}:
        return "email"
    if channel in {"api", "hubspot"}:
        return channel
    return channel


def _disabled_auto_reply_channels() -> set[str]:
    raw = getattr(settings, "HUBSPOT_AI_REPLY_DISABLED_CHANNELS", "whatsapp")
    return {normalize_channel(item) for item in str(raw).split(",") if item.strip()}


def can_send_automated_reply(channel: str | None) -> bool:
    """Return whether Judah is allowed to send automated replies on a channel."""
    normalized = normalize_channel(channel)
    if normalized == "unknown":
        return True
    return normalized not in _disabled_auto_reply_channels()


__all__ = ["can_send_automated_reply", "normalize_channel"]
