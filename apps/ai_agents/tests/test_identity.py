"""Deterministic customer identity resolution tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.ai_agents.services.identity import (
    identity_collection_message,
    normalize_phone,
    resolve_customer_identity,
)


def _profile(contact_id: str, *, email: str = "", phone: str = "", name: str = "Maria") -> dict:
    return {
        "id": contact_id,
        "properties": {
            "email": email,
            "firstname": name,
            "hs_whatsapp_phone_number": phone,
        },
    }


def _context(*, contacts: list[dict], contact_ids: list[str] | None = None) -> dict:
    return {
        "church_id": "T35120",
        "contact_ids": contact_ids if contact_ids is not None else [str(item["id"]) for item in contacts],
        "contact_profiles": contacts,
        "conversation_history": [
            {
                "id": "incoming-1",
                "direction": "INCOMING",
                "text": "Preciso de ajuda",
                "senders": [],
            }
        ],
    }


def test_normalize_phone_unifies_local_and_country_code() -> None:
    assert normalize_phone("(21) 99999-1234") == "5521999991234"
    assert normalize_phone("+55 21 99999-1234") == "5521999991234"


@pytest.mark.asyncio
async def test_delivery_identifier_verifies_unique_contact() -> None:
    context = _context(contacts=[_profile("contact-1", phone="+55 21 99999-1234")])
    context["associated_contact_id"] = "contact-1"
    context["conversation_history"][0]["senders"] = [
        {"deliveryIdentifiers": [{"type": "PHONE_NUMBER", "value": "(21) 99999-1234"}]}
    ]

    identity = await resolve_customer_identity(context)

    assert identity.status == "VERIFIED"
    assert identity.contact_id == "contact-1"
    assert identity.sensitive_actions_allowed is True
    assert identity.masked_name == "Ma***"


@pytest.mark.asyncio
async def test_multiple_ticket_contacts_are_ambiguous_not_first_match() -> None:
    context = _context(
        contacts=[_profile("contact-1"), _profile("contact-2")],
    )

    identity = await resolve_customer_identity(context)

    assert identity.status == "AMBIGUOUS"
    assert identity.contact_id is None
    assert identity.matched_by == "multiple_ticket_contacts"


@pytest.mark.asyncio
async def test_thread_association_is_probable_without_participant_proof() -> None:
    context = _context(contacts=[_profile("contact-1")])
    context["associated_contact_id"] = "contact-1"

    identity = await resolve_customer_identity(context)

    assert identity.status == "PROBABLE"
    assert identity.contact_id == "contact-1"
    assert identity.sensitive_actions_allowed is False


@pytest.mark.asyncio
async def test_thread_and_ticket_contact_conflict_fails_closed() -> None:
    context = _context(contacts=[_profile("ticket-contact")])
    context["associated_contact_id"] = "thread-contact"

    identity = await resolve_customer_identity(context)

    assert identity.status == "CONFLICT"
    assert identity.contact_id is None


@pytest.mark.asyncio
async def test_customer_email_can_disambiguate_but_does_not_verify_ownership() -> None:
    context = _context(contacts=[], contact_ids=[])
    context["conversation_history"][0]["text"] = "Meu e-mail é pessoa@igreja.org.br"
    search = AsyncMock(return_value=[_profile("contact-9", email="pessoa@igreja.org.br", name="Joana")])

    identity = await resolve_customer_identity(context, contact_search=search)

    assert identity.status == "PROBABLE"
    assert identity.contact_id == "contact-9"
    assert identity.matched_by == "crm_email_search"
    assert identity.sensitive_actions_allowed is False
    search.assert_awaited_once_with("pessoa@igreja.org.br")


@pytest.mark.asyncio
async def test_unknown_identity_requests_one_safe_datum() -> None:
    identity = await resolve_customer_identity(_context(contacts=[], contact_ids=[]))

    message = identity_collection_message(identity)

    assert identity.status == "UNKNOWN"
    assert identity.missing_fields == ["registered_email"]
    assert "e-mail cadastrado" in message
    assert "telefone" not in message.lower()


@pytest.mark.asyncio
async def test_customer_can_confirm_ticket_church_for_general_support() -> None:
    context = _context(contacts=[], contact_ids=[])
    context["conversation_history"][0]["text"] = "O código da igreja é T35120"

    identity = await resolve_customer_identity(context)

    assert identity.status == "PROBABLE"
    assert identity.church_id == "T35120"
    assert identity.matched_by == "customer_confirmed_church"
    assert identity.sensitive_actions_allowed is False


@pytest.mark.asyncio
async def test_verified_identity_is_reused_only_inside_same_conversation_context() -> None:
    context = _context(contacts=[], contact_ids=[])
    context["previous_customer_identity"] = {
        "status": "VERIFIED",
        "contact_id": "contact-verified",
        "church_id": "T35120",
        "confidence": 0.98,
        "matched_by": "delivery_identifier",
    }

    identity = await resolve_customer_identity(context, collection_attempts=1)

    assert identity.status == "VERIFIED"
    assert identity.contact_id == "contact-verified"
    assert identity.matched_by == "conversation_identity_memory"
    assert identity.collection_attempts == 1
