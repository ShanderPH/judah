"""Tests for the read-only assignment recovery audit."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from django.core.management.base import CommandError

from apps.support.management.commands.audit_assignment_recovery_candidates import Command
from apps.webhooks.models import WebhookEvent


def test_recovery_audit_requires_aware_timestamp() -> None:
    with pytest.raises(CommandError, match="timezone-aware"):
        Command._parse_since("2026-07-30T12:00:00")


@pytest.mark.django_db
def test_recovery_audit_classifies_current_provider_state_without_mutation() -> None:
    for ticket_id in ("still-new", "assigned", "left-new", "unavailable"):
        WebhookEvent.objects.create(
            event_type="ticket.propertyChange",
            object_id=ticket_id,
            property_name="hs_v2_date_entered_939275049",
            property_value="1783022705000",
            event_id=f"event-{ticket_id}",
            payload={},
        )
    client = Mock()

    def ticket_details(ticket_id: str) -> dict[str, str]:
        if ticket_id == "still-new":
            return {
                "pipeline": "636459134",
                "hs_pipeline_stage": "939275049",
                "hubspot_owner_id": "",
            }
        if ticket_id == "assigned":
            return {"hubspot_owner_id": "owner-1"}
        if ticket_id == "left-new":
            return {"pipeline": "other", "hs_pipeline_stage": "other"}
        raise RuntimeError("provider unavailable")

    client.get_ticket_details.side_effect = ticket_details
    with patch("apps.integrations.hubspot.client.get_hubspot_client", return_value=client):
        report = Command._classify(
            since=datetime(2026, 7, 30, tzinfo=UTC),
            limit=10,
        )

    assert report["mode"] == "read_only"
    assert report["counts"] == {
        "still_new_without_owner": 1,
        "assigned_elsewhere": 1,
        "left_new_stage": 1,
        "ambiguous_quarantine": 1,
    }
    assert WebhookEvent.objects.count() == 4
