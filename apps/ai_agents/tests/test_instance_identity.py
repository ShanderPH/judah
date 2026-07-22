"""Regression tests for one persisted instance per HubSpot conversation."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.execution import ensure_conversation_instance
from apps.ai_agents.services.instance_identity import find_conversation_instance


@pytest.mark.django_db
def test_two_threads_on_same_ticket_have_independent_instances() -> None:
    first = ensure_conversation_instance(
        context={"ticket_id": "ticket-1", "thread_ids": ["thread-1"], "contact_ids": ["contact-1"]},
        ticket_id="ticket-1",
        session_id="hubspot-thread-thread-1",
    )
    second = ensure_conversation_instance(
        context={"ticket_id": "ticket-1", "thread_ids": ["thread-2"], "contact_ids": ["contact-1"]},
        ticket_id="ticket-1",
        session_id="hubspot-thread-thread-2",
    )

    assert first.pk != second.pk
    assert first.hubspot_ticket_id == second.hubspot_ticket_id == "ticket-1"
    assert first.ai_session_id == "hubspot-thread-thread-1"
    assert second.ai_session_id == "hubspot-thread-thread-2"
    assert ConversationInstance.objects.filter(hubspot_ticket_id="ticket-1").count() == 2


@pytest.mark.django_db
def test_thread_lookup_never_falls_back_to_another_thread_on_same_ticket() -> None:
    existing = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:thread-existing",
        hubspot_thread_id="thread-existing",
        hubspot_ticket_id="ticket-shared",
    )

    assert find_conversation_instance(thread_id="thread-missing", ticket_id="ticket-shared") is None
    assert find_conversation_instance(thread_id="thread-existing", ticket_id="ticket-shared") == existing
    assert find_conversation_instance(ticket_id="ticket-shared") is None


@pytest.mark.django_db
def test_ticket_placeholder_is_separate_from_conversation_threads() -> None:
    thread_instance = ensure_conversation_instance(
        context={"ticket_id": "ticket-2", "thread_ids": ["thread-2"]},
        ticket_id="ticket-2",
        session_id="hubspot-thread-thread-2",
    )
    ticket_instance = ensure_conversation_instance(
        context={"ticket_id": "ticket-2", "thread_ids": []},
        ticket_id="ticket-2",
        session_id="hubspot-ticket-ticket-2",
    )

    assert ticket_instance.pk != thread_instance.pk
    assert ticket_instance.hubspot_thread_id is None
    assert ensure_conversation_instance(
        context={"ticket_id": "ticket-2", "thread_ids": []},
        ticket_id="ticket-2",
        session_id="hubspot-ticket-ticket-2",
    ).pk == ticket_instance.pk


@pytest.mark.django_db
def test_thread_identifier_remains_unique() -> None:
    ConversationInstance.objects.create(
        idempotency_key="conversation:thread:unique-thread",
        hubspot_thread_id="unique-thread",
        hubspot_ticket_id="ticket-a",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ConversationInstance.objects.create(
            idempotency_key="conversation:thread:duplicate-thread",
            hubspot_thread_id="unique-thread",
            hubspot_ticket_id="ticket-b",
        )


@pytest.mark.django_db
def test_existing_thread_instance_is_hydrated_without_changing_identity() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:hydrate-thread",
        hubspot_thread_id="hydrate-thread",
        ai_session_id="hubspot-thread-hydrate-thread",
    )

    hydrated = ensure_conversation_instance(
        context={
            "ticket_id": "ticket-hydrated",
            "thread_ids": ["hydrate-thread"],
            "contact_ids": ["contact-hydrated"],
            "originating_channel": "CHAT",
            "pipeline": "pipeline-1",
            "pipeline_stage": "stage-1",
        },
        ticket_id="ticket-hydrated",
        session_id="hubspot-thread-hydrate-thread",
    )

    assert hydrated.pk == instance.pk
    assert hydrated.hubspot_ticket_id == "ticket-hydrated"
    assert hydrated.hubspot_contact_id == "contact-hydrated"
    assert hydrated.pipeline_id == "pipeline-1"


@pytest.mark.django_db
def test_hydration_tracks_latest_incoming_message_as_turn_identity() -> None:
    instance = ensure_conversation_instance(
        context={
            "ticket_id": "ticket-turn",
            "thread_ids": ["thread-turn"],
            "conversation_history": [
                {"id": "incoming-1", "direction": "INCOMING", "text": "Primeira"},
                {"id": "outgoing-1", "direction": "OUTGOING", "text": "Resposta"},
                {"id": "incoming-2", "direction": "INCOMING", "text": "Segunda"},
            ],
        },
        ticket_id="ticket-turn",
        session_id="hubspot-thread-thread-turn",
    )

    assert instance.last_message_id == "incoming-2"
    assert instance.metadata["latest_customer_turn"]["message_count"] == 1
    assert instance.metadata["latest_customer_turn"]["message_ids"] == ["incoming-2"]


@pytest.mark.django_db
def test_hydration_audits_consecutive_messages_as_one_customer_turn() -> None:
    instance = ensure_conversation_instance(
        context={
            "ticket_id": "ticket-batch",
            "thread_ids": ["thread-batch"],
            "conversation_history": [
                {"id": "outgoing-1", "direction": "OUTGOING", "text": "Como posso ajudar?"},
                {"id": "incoming-1", "direction": "INCOMING", "text": "Tenho interesse"},
                {"id": "incoming-2", "direction": "INCOMING", "text": "nos planos e valores"},
            ],
        },
        ticket_id="ticket-batch",
        session_id="hubspot-thread-thread-batch",
    )

    assert instance.last_message_id == "incoming-2"
    assert instance.metadata["latest_customer_turn"] == {
        "message_count": 2,
        "message_ids": ["incoming-1", "incoming-2"],
        "first_message_id": "incoming-1",
        "last_message_id": "incoming-2",
        "first_created_at": None,
        "last_created_at": None,
    }


@pytest.mark.django_db
def test_hydration_fingerprints_distinct_turns_when_hubspot_omits_message_id() -> None:
    base_context = {
        "ticket_id": "ticket-fingerprint",
        "thread_ids": ["thread-fingerprint"],
        "conversation_history": [
            {
                "direction": "INCOMING",
                "text": "Primeira",
                "sender": "visitor-1",
                "created_at": "2026-07-22T12:00:00Z",
            }
        ],
    }
    instance = ensure_conversation_instance(
        context=base_context,
        ticket_id="ticket-fingerprint",
        session_id="hubspot-thread-thread-fingerprint",
    )
    first_turn_id = instance.last_message_id

    base_context["conversation_history"].append(
        {
            "direction": "INCOMING",
            "text": "Segunda",
            "sender": "visitor-1",
            "created_at": "2026-07-22T12:01:00Z",
        }
    )
    ensure_conversation_instance(
        context=base_context,
        ticket_id="ticket-fingerprint",
        session_id="hubspot-thread-thread-fingerprint",
    )
    instance.refresh_from_db()

    assert first_turn_id.startswith("sha256:")
    assert instance.last_message_id.startswith("sha256:")
    assert instance.last_message_id != first_turn_id
