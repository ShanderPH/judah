"""Tests for support ticket business services."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.support.models import Ticket
from apps.support.schemas import CreateTicketRequest, UpdateTicketRequest
from apps.support.services import create_ticket, get_ticket, list_tickets, update_ticket
from common.exceptions import NotFoundError


@pytest.mark.django_db
def test_ticket_create_get_list_and_update() -> None:
    created_at = datetime(2026, 7, 15, tzinfo=UTC)
    ticket = create_ticket(
        CreateTicketRequest(
            ticket_id="EXT-1",
            customer_name="Cliente",
            ticket_church="Igreja",
            category="login",
            priority="high",
            status="open",
            created_at=created_at,
        )
    )
    Ticket.objects.create(ticket_id="EXT-2", priority="low", status="closed", created_at=created_at)

    assert get_ticket(ticket.pk) == ticket
    assert get_ticket("EXT-1") == ticket
    assert list_tickets(status="open", church="Igreja", priority="high") == [ticket]

    updated = update_ticket(
        ticket.pk,
        UpdateTicketRequest(
            status="closed",
            priority="urgent",
            category="security",
            affected_device="mobile",
            scope_of_impact="one user",
            affected_module="auth",
            affected_functionality="login",
            closed_at=created_at,
        ),
    )
    assert updated.status == "closed"
    assert updated.affected_module == "auth"
    assert update_ticket(ticket.pk, UpdateTicketRequest()) == updated


@pytest.mark.django_db
def test_get_ticket_maps_missing_identifiers() -> None:
    with pytest.raises(NotFoundError):
        get_ticket(uuid4())
    with pytest.raises(NotFoundError):
        get_ticket("missing")
