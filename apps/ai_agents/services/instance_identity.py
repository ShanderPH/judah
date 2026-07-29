"""Canonical identity rules for persisted conversation instances."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance, ConversationStateTransition

SUPERSEDED_KEY_PREFIX = "conversation:superseded:"


def ticket_scope_instances(ticket_id: str) -> QuerySet[ConversationInstance]:
    """Return ticket-level placeholders, never a concrete conversation thread."""
    return (
        ConversationInstance.objects.filter(hubspot_ticket_id=str(ticket_id))
        .filter(Q(hubspot_thread_id__isnull=True) | Q(hubspot_thread_id=""))
        .exclude(idempotency_key__startswith=SUPERSEDED_KEY_PREFIX)
    )


def canonical_thread_instances(ticket_id: str) -> QuerySet[ConversationInstance]:
    """Return non-superseded concrete conversation identities for a ticket."""
    return (
        ConversationInstance.objects.filter(hubspot_ticket_id=str(ticket_id))
        .exclude(Q(hubspot_thread_id__isnull=True) | Q(hubspot_thread_id=""))
        .exclude(idempotency_key__startswith=SUPERSEDED_KEY_PREFIX)
    )


def _supersede_placeholder(
    placeholder: ConversationInstance,
    *,
    canonical: ConversationInstance,
    reason: str,
) -> None:
    """Terminalize a duplicate placeholder while preserving its complete audit."""
    now = timezone.now()
    old_state = placeholder.state
    metadata = dict(placeholder.metadata or {})
    metadata["identity_supersession"] = {
        "canonical_instance_id": str(canonical.pk),
        "canonical_thread_id": canonical.hubspot_thread_id,
        "reason": reason,
        "superseded_at": now.isoformat(),
    }
    placeholder.metadata = metadata
    placeholder.idempotency_key = f"{SUPERSEDED_KEY_PREFIX}{placeholder.pk}"
    placeholder.state = ConversationInstance.State.IGNORED
    placeholder.state_version += 1
    placeholder.last_activity_at = now
    placeholder.failure_count = 0
    placeholder.next_retry_at = None
    placeholder.current_error = ""
    placeholder.save(
        update_fields=[
            "metadata",
            "idempotency_key",
            "state",
            "state_version",
            "last_activity_at",
            "failure_count",
            "next_retry_at",
            "current_error",
            "updated_at",
        ]
    )
    ConversationStateTransition.objects.create(
        instance=placeholder,
        from_state=old_state,
        to_state=ConversationInstance.State.IGNORED,
        reason=f"Conversation identity superseded: {reason}.",
        actor_type="identity_reconciliation",
        actor_id=str(canonical.pk),
    )


def promote_or_get_thread_instance(
    *,
    ticket_id: str | None,
    thread_id: str,
) -> ConversationInstance | None:
    """Atomically promote a ticket placeholder or converge it into a thread.

    Returning ``None`` means no persisted identity exists yet and the caller
    may create the canonical thread instance.
    """
    normalized_thread_id = str(thread_id).strip()
    normalized_ticket_id = str(ticket_id or "").strip()
    if not normalized_thread_id:
        return None

    with transaction.atomic():
        canonical = (
            ConversationInstance.objects.select_for_update().filter(hubspot_thread_id=normalized_thread_id).first()
        )
        placeholders = (
            list(ticket_scope_instances(normalized_ticket_id).select_for_update().order_by("created_at", "pk"))
            if normalized_ticket_id
            else []
        )
        if canonical is not None:
            for placeholder in placeholders:
                _supersede_placeholder(
                    placeholder,
                    canonical=canonical,
                    reason="canonical_thread_already_exists",
                )
            return canonical

        if not placeholders:
            return None

        canonical = placeholders[0]
        now = timezone.now()
        metadata = dict(canonical.metadata or {})
        promotions = list(metadata.get("identity_promotions") or [])
        promotions.append(
            {
                "from": f"ticket:{normalized_ticket_id}",
                "to": f"thread:{normalized_thread_id}",
                "promoted_at": now.isoformat(),
            }
        )
        metadata["identity_promotions"] = promotions[-10:]
        canonical.hubspot_thread_id = normalized_thread_id
        canonical.idempotency_key = f"conversation:thread:{normalized_thread_id}"
        canonical.metadata = metadata
        canonical.last_activity_at = now
        canonical.save(
            update_fields=[
                "hubspot_thread_id",
                "idempotency_key",
                "metadata",
                "last_activity_at",
                "updated_at",
            ]
        )
        for placeholder in placeholders[1:]:
            _supersede_placeholder(
                placeholder,
                canonical=canonical,
                reason="duplicate_ticket_placeholder",
            )
        return canonical


def supersede_placeholder_if_canonical_exists(instance: ConversationInstance) -> ConversationInstance | None:
    """Supersede one irrecoverable ticket placeholder when a canonical row exists."""
    if instance.hubspot_thread_id or not instance.hubspot_ticket_id:
        return None
    with transaction.atomic():
        placeholder = ConversationInstance.objects.select_for_update().get(pk=instance.pk)
        canonical = (
            canonical_thread_instances(str(placeholder.hubspot_ticket_id))
            .select_for_update()
            .order_by("-last_activity_at", "-created_at")
            .first()
        )
        if canonical is None:
            return None
        _supersede_placeholder(
            placeholder,
            canonical=canonical,
            reason="watchdog_found_canonical_thread",
        )
        return canonical


def find_conversation_instance(
    *,
    thread_id: str | None = None,
    ticket_id: str | None = None,
) -> ConversationInstance | None:
    """Resolve one instance without falling from a thread into another conversation."""
    normalized_thread_id = str(thread_id or "").strip()
    if normalized_thread_id:
        return ConversationInstance.objects.filter(hubspot_thread_id=normalized_thread_id).first()

    normalized_ticket_id = str(ticket_id or "").strip()
    if normalized_ticket_id:
        placeholder = ticket_scope_instances(normalized_ticket_id).first()
        if placeholder is not None:
            return placeholder
        canonical = list(canonical_thread_instances(normalized_ticket_id).order_by("-last_activity_at")[:2])
        return canonical[0] if len(canonical) == 1 else None
    return None


def conversation_idempotency_key(
    *,
    thread_id: str | None = None,
    ticket_id: str | None = None,
    session_id: str,
) -> str:
    """Build the stable persistence key for a thread or ticket-level placeholder."""
    normalized_thread_id = str(thread_id or "").strip()
    if normalized_thread_id:
        return f"conversation:thread:{normalized_thread_id}"
    normalized_ticket_id = str(ticket_id or "").strip()
    if normalized_ticket_id:
        return f"conversation:ticket:{normalized_ticket_id}"
    return f"conversation:session:{session_id}"


__all__ = [
    "SUPERSEDED_KEY_PREFIX",
    "canonical_thread_instances",
    "conversation_idempotency_key",
    "find_conversation_instance",
    "promote_or_get_thread_instance",
    "supersede_placeholder_if_canonical_exists",
    "ticket_scope_instances",
]
