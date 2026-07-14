"""Deterministic rollout policy for AI-routed conversations."""

from __future__ import annotations

import hashlib

from django.conf import settings


def is_ai_rollout_enabled(identifier: str) -> bool:
    """Return whether an identifier belongs to the configured AI rollout cohort."""
    percentage = max(0, min(100, int(getattr(settings, "AI_ROUTING_ROLLOUT_PERCENTAGE", 100))))
    if percentage == 0:
        return False
    if percentage == 100:
        return True
    bucket = int(hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < percentage


__all__ = ["is_ai_rollout_enabled"]
