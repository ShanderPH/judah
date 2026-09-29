"""Classify support assignment origin from persisted evidence."""

from __future__ import annotations

from enum import StrEnum


class AssignmentProvenance(StrEnum):
    """Stable domain vocabulary for an observed owner effect."""

    AUTOMATIC_ASSIGNMENT = "automatic_assignment"
    MANUAL_ASSIGNMENT = "manual_assignment"
    OWNER_CHANGE = "owner_change"
    FORCED_REASSIGNMENT = "forced_reassignment"
    EXTERNAL_INTEGRATION = "external_integration"
    UNKNOWN_EXTERNAL = "unknown_external"


def classify_owner_effect(
    *,
    attempt_type: str | None = None,
    administrative_reassignment: bool = False,
    verified_external_integration: bool = False,
    verified_owner_actor: bool = False,
) -> AssignmentProvenance:
    """Assign a specific origin only when the matching evidence is present."""
    if attempt_type == "automatic":
        return AssignmentProvenance.AUTOMATIC_ASSIGNMENT
    if attempt_type == "manual":
        return AssignmentProvenance.MANUAL_ASSIGNMENT
    if attempt_type == "forced" or administrative_reassignment:
        return AssignmentProvenance.FORCED_REASSIGNMENT
    if verified_external_integration:
        return AssignmentProvenance.EXTERNAL_INTEGRATION
    if verified_owner_actor:
        return AssignmentProvenance.OWNER_CHANGE
    return AssignmentProvenance.UNKNOWN_EXTERNAL


def administrative_source(reason: str | None = None, *, reserved: bool = False) -> str:
    """Keep the administrative reason beside its stable provenance prefix."""
    parts = [str(classify_owner_effect(administrative_reassignment=True))]
    if reserved:
        parts.append("reserved")
    if reason:
        parts.append(reason)
    return ":".join(parts)
