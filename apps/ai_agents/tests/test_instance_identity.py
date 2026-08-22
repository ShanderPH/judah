import pytest

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.instance_identity import (
    conversation_idempotency_key,
    find_conversation_instance,
    promote_or_get_thread_instance,
    supersede_placeholder_if_canonical_exists,
)


def test_conversation_idempotency_prefers_thread() -> None:
    assert (
        conversation_idempotency_key(thread_id="thread-1", ticket_id="ticket-1", session_id="session-1")
        == "conversation:thread:thread-1"
    )
    assert conversation_idempotency_key(ticket_id="ticket-1", session_id="session-1") == (
        "conversation:ticket:ticket-1"
    )
    assert conversation_idempotency_key(session_id="session-1") == "conversation:session:session-1"


@pytest.mark.django_db
def test_ticket_placeholder_promotes_to_canonical_thread() -> None:
    placeholder = ConversationInstance.objects.create(
        idempotency_key="conversation:ticket:ticket-1",
        hubspot_ticket_id="ticket-1",
    )

    promoted = promote_or_get_thread_instance(ticket_id="ticket-1", thread_id="thread-1")

    assert promoted is not None
    assert promoted.pk == placeholder.pk
    assert promoted.hubspot_thread_id == "thread-1"
    assert find_conversation_instance(thread_id="thread-1") == promoted


@pytest.mark.django_db
def test_existing_canonical_supersedes_ticket_placeholder() -> None:
    canonical = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:thread-2",
        hubspot_thread_id="thread-2",
        hubspot_ticket_id="ticket-2",
    )
    placeholder = ConversationInstance.objects.create(
        idempotency_key="conversation:ticket:ticket-2",
        hubspot_ticket_id="ticket-2",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=2,
    )

    resolved = promote_or_get_thread_instance(ticket_id="ticket-2", thread_id="thread-2")

    placeholder.refresh_from_db()
    assert resolved == canonical
    assert placeholder.state == ConversationInstance.State.IGNORED
    assert placeholder.failure_count == 0
    assert placeholder.metadata["identity_supersession"]["canonical_instance_id"] == str(canonical.pk)


@pytest.mark.django_db
def test_watchdog_supersedes_placeholder_only_when_canonical_exists() -> None:
    orphan = ConversationInstance.objects.create(
        idempotency_key="conversation:ticket:ticket-orphan",
        hubspot_ticket_id="ticket-orphan",
    )
    assert supersede_placeholder_if_canonical_exists(orphan) is None

    canonical = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:thread-orphan",
        hubspot_thread_id="thread-orphan",
        hubspot_ticket_id="ticket-orphan",
    )
    assert supersede_placeholder_if_canonical_exists(orphan) == canonical
    assert supersede_placeholder_if_canonical_exists(canonical) is None


@pytest.mark.django_db
def test_ticket_lookup_rejects_ambiguous_canonical_threads() -> None:
    for suffix in ("a", "b"):
        ConversationInstance.objects.create(
            idempotency_key=f"conversation:thread:{suffix}",
            hubspot_thread_id=f"thread-{suffix}",
            hubspot_ticket_id="ticket-shared",
        )

    assert find_conversation_instance(ticket_id="ticket-shared") is None
    assert find_conversation_instance() is None
    assert promote_or_get_thread_instance(ticket_id="ticket-shared", thread_id="") is None
