"""Deterministic, privacy-safe customer identity resolution for HubSpot chats.

An association between a ticket and a contact is useful CRM context, but it is
not proof that the associated person is the participant who sent the current
message. This module resolves that distinction without asking an LLM to infer
identity and without persisting raw contact PII in lifecycle metadata.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from apps.ai_agents.contracts import CustomerIdentity
from apps.ai_agents.services.conversation_turn import current_incoming_turn

ContactSearch = Callable[[str], Awaitable[list[dict[str, Any]]]]
IdentityStatus = Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN", "CONFLICT"]

_EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.IGNORECASE)
_CHURCH_ID_RE = re.compile(
    r"(?:c[oó]digo(?:\s+da)?\s+igreja|igreja)\D{0,12}(T?\s*\d{3,})",
    re.IGNORECASE,
)


def normalize_email(value: Any) -> str:
    """Normalize an email solely for deterministic equality checks."""
    return str(value or "").strip().casefold()


def normalize_phone(value: Any) -> str:
    """Normalize Brazilian/local phone variants to a stable digit sequence."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) in {10, 11}:
        digits = f"55{digits}"
    return digits


def _masked_name(profile: dict[str, Any] | None) -> str | None:
    properties = (profile or {}).get("properties") or {}
    first_name = str(properties.get("firstname") or "").strip()
    if not first_name:
        return None
    normalized = unicodedata.normalize("NFC", first_name)
    if len(normalized) <= 2:
        return f"{normalized[0]}*" if normalized else None
    return f"{normalized[:2]}{'*' * min(len(normalized) - 2, 5)}"


def _current_customer_text(context: dict[str, Any]) -> str:
    return "\n".join(str(message.get("text") or "") for message in current_incoming_turn(context)).strip()


def _stated_email(context: dict[str, Any]) -> str:
    match = _EMAIL_RE.search(_current_customer_text(context))
    return normalize_email(match.group(1)) if match else ""


def _normalize_church_id(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _stated_church_id(context: dict[str, Any]) -> str:
    match = _CHURCH_ID_RE.search(_current_customer_text(context))
    return _normalize_church_id(match.group(1)) if match else ""


def _delivery_identifiers(context: dict[str, Any]) -> tuple[set[str], set[str]]:
    emails: set[str] = set()
    phones: set[str] = set()
    for message in current_incoming_turn(context):
        for sender in message.get("senders") or []:
            identifiers = list(sender.get("deliveryIdentifiers") or [])
            if sender.get("deliveryIdentifier"):
                identifiers.append(sender["deliveryIdentifier"])
            for identifier in identifiers:
                identifier_type = str(identifier.get("type") or "").upper()
                value = identifier.get("value")
                if "EMAIL" in identifier_type:
                    normalized = normalize_email(value)
                    if normalized:
                        emails.add(normalized)
                elif "PHONE" in identifier_type or "WHATSAPP" in identifier_type:
                    normalized = normalize_phone(value)
                    if normalized:
                        phones.add(normalized)
    return emails, phones


def _profile_values(profile: dict[str, Any]) -> tuple[set[str], set[str]]:
    properties = profile.get("properties") or {}
    emails = {normalize_email(properties.get("email"))} - {""}
    phones = {
        normalize_phone(properties.get("phone")),
        normalize_phone(properties.get("mobilephone")),
        normalize_phone(properties.get("hs_whatsapp_phone_number")),
    } - {""}
    return emails, phones


def _contact_id(profile: dict[str, Any]) -> str:
    return str(profile.get("id") or "").strip()


def _identity(
    *,
    status: IdentityStatus,
    contact_id: str | None,
    church_id: str | None,
    confidence: float,
    matched_by: str,
    evidence: list[str],
    missing_fields: list[str],
    profile: dict[str, Any] | None = None,
    collection_attempts: int = 0,
) -> CustomerIdentity:
    return CustomerIdentity(
        status=status,
        contact_id=contact_id,
        church_id=church_id,
        confidence=confidence,
        matched_by=matched_by,
        evidence=evidence,
        missing_fields=missing_fields,
        masked_name=_masked_name(profile),
        collection_attempts=collection_attempts,
    )


async def resolve_customer_identity(
    context: dict[str, Any],
    *,
    contact_search: ContactSearch | None = None,
    collection_attempts: int = 0,
) -> CustomerIdentity:
    """Resolve the active customer from independent HubSpot evidence.

    Delivery identifiers from the current incoming message are the strongest
    available proof. A ticket or thread association without a matching sender
    identifier remains probable, never verified. A customer-entered email can
    disambiguate a CRM record, but is still self-asserted and therefore cannot
    authorize sensitive actions.
    """
    church_id = str(context.get("church_id") or "").strip() or None
    associated_contact_id = str(context.get("associated_contact_id") or "").strip()
    contact_ids = [str(value) for value in context.get("contact_ids") or [] if str(value).strip()]
    profiles = [profile for profile in context.get("contact_profiles") or [] if _contact_id(profile)]
    profiles_by_id = {_contact_id(profile): profile for profile in profiles}
    delivery_emails, delivery_phones = _delivery_identifiers(context)

    delivery_matches: list[dict[str, Any]] = []
    for profile in profiles:
        profile_emails, profile_phones = _profile_values(profile)
        if delivery_emails.intersection(profile_emails) or delivery_phones.intersection(profile_phones):
            delivery_matches.append(profile)

    if len(delivery_matches) == 1:
        profile = delivery_matches[0]
        return _identity(
            status="VERIFIED",
            contact_id=_contact_id(profile),
            church_id=church_id,
            confidence=0.98,
            matched_by="delivery_identifier",
            evidence=["incoming_delivery_identifier_matches_contact"],
            missing_fields=[],
            profile=profile,
            collection_attempts=collection_attempts,
        )
    if len(delivery_matches) > 1:
        return _identity(
            status="AMBIGUOUS",
            contact_id=None,
            church_id=church_id,
            confidence=0.2,
            matched_by="delivery_identifier_multiple",
            evidence=["incoming_delivery_identifier_matches_multiple_contacts"],
            missing_fields=["registered_email"],
            collection_attempts=collection_attempts,
        )

    stated_email = _stated_email(context)
    stated_matches = (
        [profile for profile in profiles if stated_email in _profile_values(profile)[0]] if stated_email else []
    )
    if len(stated_matches) == 1:
        profile = stated_matches[0]
        return _identity(
            status="PROBABLE",
            contact_id=_contact_id(profile),
            church_id=church_id,
            confidence=0.82,
            matched_by="customer_stated_email",
            evidence=["customer_stated_email_matches_contact"],
            missing_fields=[],
            profile=profile,
            collection_attempts=collection_attempts,
        )
    if len(stated_matches) > 1:
        return _identity(
            status="AMBIGUOUS",
            contact_id=None,
            church_id=church_id,
            confidence=0.2,
            matched_by="customer_stated_email_multiple",
            evidence=["customer_stated_email_matches_multiple_contacts"],
            missing_fields=["human_identity_validation"],
            collection_attempts=collection_attempts,
        )

    if stated_email and contact_search is not None:
        searched = await contact_search(stated_email)
        unique = [profile for profile in searched if _contact_id(profile)]
        if len(unique) == 1:
            profile = unique[0]
            return _identity(
                status="PROBABLE",
                contact_id=_contact_id(profile),
                church_id=church_id,
                confidence=0.75,
                matched_by="crm_email_search",
                evidence=["customer_stated_email_has_unique_crm_match"],
                missing_fields=[],
                profile=profile,
                collection_attempts=collection_attempts,
            )
        if len(unique) > 1:
            return _identity(
                status="AMBIGUOUS",
                contact_id=None,
                church_id=church_id,
                confidence=0.15,
                matched_by="crm_email_search_multiple",
                evidence=["customer_stated_email_has_multiple_crm_matches"],
                missing_fields=["human_identity_validation"],
                collection_attempts=collection_attempts,
            )

    stated_church_id = _stated_church_id(context)
    expected_church_id = _normalize_church_id(church_id)
    if stated_church_id:
        if expected_church_id and stated_church_id != expected_church_id:
            return _identity(
                status="CONFLICT",
                contact_id=None,
                church_id=church_id,
                confidence=0.1,
                matched_by="customer_stated_church_conflict",
                evidence=["customer_stated_church_differs_from_ticket"],
                missing_fields=["registered_email"],
                collection_attempts=collection_attempts,
            )
        likely_contact_id = associated_contact_id or (contact_ids[0] if len(contact_ids) == 1 else None)
        return _identity(
            status="PROBABLE",
            contact_id=likely_contact_id,
            church_id=church_id or stated_church_id,
            confidence=0.72 if likely_contact_id else 0.6,
            matched_by="customer_confirmed_church",
            evidence=["customer_stated_church_matches_ticket" if church_id else "customer_stated_church"],
            missing_fields=[],
            profile=profiles_by_id.get(likely_contact_id or ""),
            collection_attempts=collection_attempts,
        )

    previous_payload = context.get("previous_customer_identity")
    if isinstance(previous_payload, dict):
        try:
            previous = CustomerIdentity.model_validate(previous_payload)
        except ValueError:
            previous = None
        if previous is not None and previous.status in {"VERIFIED", "PROBABLE"} and previous.contact_id:
            if contact_ids and previous.contact_id not in contact_ids and previous.contact_id != associated_contact_id:
                return _identity(
                    status="CONFLICT",
                    contact_id=None,
                    church_id=church_id or previous.church_id,
                    confidence=0.1,
                    matched_by="conversation_identity_conflict",
                    evidence=["previous_contact_differs_from_current_associations"],
                    missing_fields=["registered_email"],
                    collection_attempts=collection_attempts,
                )
            return previous.model_copy(
                update={
                    "matched_by": "conversation_identity_memory",
                    "collection_attempts": collection_attempts,
                    "church_id": church_id or previous.church_id,
                }
            )

    if associated_contact_id:
        if contact_ids and associated_contact_id not in contact_ids:
            return _identity(
                status="CONFLICT",
                contact_id=None,
                church_id=church_id,
                confidence=0.1,
                matched_by="thread_ticket_conflict",
                evidence=["thread_contact_differs_from_ticket_contacts"],
                missing_fields=["registered_email"],
                collection_attempts=collection_attempts,
            )
        profile = profiles_by_id.get(associated_contact_id)
        return _identity(
            status="PROBABLE",
            contact_id=associated_contact_id,
            church_id=church_id,
            confidence=0.78 if profile else 0.7,
            matched_by="thread_association",
            evidence=["thread_has_unique_associated_contact"],
            missing_fields=[],
            profile=profile,
            collection_attempts=collection_attempts,
        )

    unique_contact_ids = list(dict.fromkeys(contact_ids))
    if len(unique_contact_ids) == 1:
        contact_id = unique_contact_ids[0]
        return _identity(
            status="PROBABLE",
            contact_id=contact_id,
            church_id=church_id,
            confidence=0.65,
            matched_by="ticket_association",
            evidence=["ticket_has_unique_associated_contact"],
            missing_fields=[],
            profile=profiles_by_id.get(contact_id),
            collection_attempts=collection_attempts,
        )
    if len(unique_contact_ids) > 1:
        return _identity(
            status="AMBIGUOUS",
            contact_id=None,
            church_id=church_id,
            confidence=0.1,
            matched_by="multiple_ticket_contacts",
            evidence=["ticket_has_multiple_associated_contacts"],
            missing_fields=["registered_email"],
            collection_attempts=collection_attempts,
        )

    return _identity(
        status="UNKNOWN",
        contact_id=None,
        church_id=church_id,
        confidence=0.0,
        matched_by="none",
        evidence=["no_contact_evidence"],
        missing_fields=["registered_email"],
        collection_attempts=collection_attempts,
    )


def identity_collection_message(identity: CustomerIdentity) -> str:
    """Return a focused, non-disclosing identity collection question."""
    if identity.status == "CONFLICT":
        prefix = "Os dados desta conversa não coincidem com o cadastro associado ao ticket."
    elif identity.status == "AMBIGUOUS":
        prefix = "Encontrei mais de um cadastro possível para esta conversa."
    else:
        prefix = "Para localizar seu cadastro com segurança, preciso confirmar uma informação."
    return f"{prefix} Por favor, informe o e-mail cadastrado na inChurch. Se não souber, envie o código da sua igreja."


__all__ = [
    "identity_collection_message",
    "normalize_email",
    "normalize_phone",
    "resolve_customer_identity",
]
