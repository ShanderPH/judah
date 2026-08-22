"""Provider-neutral channel normalization for lifecycle records."""

from __future__ import annotations


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


__all__ = ["normalize_channel"]
