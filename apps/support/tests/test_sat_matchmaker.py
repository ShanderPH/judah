"""Tests for SAT (Smart Agent Tracking) and Matchmaker services."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.support.models import (
    Agent,
    AgentAvailabilityDecision,
    AgentDailyTimeLog,
    AgentStatusHistory,
    AssignedConversation,
    AssignmentLog,
    NewConversation,
)


def _make_agent(
    name: str,
    owner_id: int,
    status: str = "online",
    chats: int = 0,
    max_chats: int = 5,
    last_status_change_at: datetime | None = None,
) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower().replace(' ', '.')}@test.com",
        hubspot_owner_id=owner_id,
        status_enum=status,
        current_simultaneous_chats=chats,
        max_simultaneous_chats=max_chats,
        auto_assign_enabled=True,
        is_active=True,
        last_status_change_at=last_status_change_at,
    )


def _make_pending_ticket(ticket_id: str, minutes_ago: int = 5) -> NewConversation:
    return NewConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        pipeline_id="636459134",
        entered_queue_at=timezone.now() - timedelta(minutes=minutes_ago),
        automatic_assignment_eligible=True,
    )


# ---------------------------------------------------------------------------
# SAT Service Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSATHeartbeat:
    @patch("apps.support.sat_service.is_business_hours", return_value=False)
    def test_skips_off_hours(self, mock_bh):
        from apps.support.sat_service import sat_heartbeat

        result = sat_heartbeat()

        assert result["skipped_off_hours"] is True
        assert result["agents_checked"] == 0

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_detects_status_change(self, mock_client_fn, mock_bh):
        agent = _make_agent("Agent1", 100, status="away", last_status_change_at=timezone.now() - timedelta(minutes=5))
        mock_client = MagicMock()
        mock_client.get_all_owners_availability.return_value = [
            {"email": agent.agent_email, "status_enum": "online"},
        ]
        mock_client_fn.return_value = mock_client

        from apps.support.sat_service import sat_heartbeat

        with patch("apps.support.tasks.task_matchmaker_drain_queue") as mock_drain:
            mock_drain.delay = MagicMock()
            result = sat_heartbeat()

        assert result["status_changes"] == 1
        assert result["agents_came_online"] == 1

        agent.refresh_from_db()
        assert agent.status_enum == "online"
        assert agent.sat_last_heartbeat_at is not None

        # Status history should be created
        history = AgentStatusHistory.objects.filter(agent=agent, sync_source="sat_heartbeat")
        assert history.count() == 1
        assert history.first().old_status == "away"
        assert history.first().new_status == "online"

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_no_change_updates_heartbeat_only(self, mock_client_fn, mock_bh):
        agent = _make_agent("Agent1", 100, status="online")
        mock_client = MagicMock()
        mock_client.get_all_owners_availability.return_value = [
            {"email": agent.agent_email, "status_enum": "online"},
        ]
        mock_client_fn.return_value = mock_client

        from apps.support.sat_service import sat_heartbeat

        first_result = sat_heartbeat()
        agent.refresh_from_db()
        first_revision = agent.availability_revision
        first_observed_at = agent.availability_observed_at
        decision_count = AgentAvailabilityDecision.objects.filter(agent=agent).count()

        result = sat_heartbeat()

        assert result["status_changes"] == 0
        assert first_result["status_changes"] == 0
        agent.refresh_from_db()
        assert agent.sat_last_heartbeat_at is not None
        assert agent.availability_observed_at >= first_observed_at
        assert agent.availability_revision == first_revision
        assert AgentAvailabilityDecision.objects.filter(agent=agent).count() == decision_count


@pytest.mark.django_db
class TestSATAccumulateTime:
    def test_accumulates_online_time(self):
        from apps.support.sat_service import sat_accumulate_time

        five_min_ago = timezone.now() - timedelta(minutes=5)
        agent = _make_agent("Agent1", 100, status="online", last_status_change_at=five_min_ago)

        now = timezone.now()
        sat_accumulate_time(agent, "online", "away", now)

        assert agent.online_time_seconds_today >= 290  # ~5 min = 300s, allow some drift
        assert agent.online_time_seconds_today <= 310

        # Daily log should be created
        log = AgentDailyTimeLog.objects.filter(agent=agent).first()
        assert log is not None
        assert log.online_time_seconds >= 290

    def test_accumulates_away_time(self):
        from apps.support.sat_service import sat_accumulate_time

        ten_min_ago = timezone.now() - timedelta(minutes=10)
        agent = _make_agent("Agent1", 100, status="away", last_status_change_at=ten_min_ago)

        now = timezone.now()
        sat_accumulate_time(agent, "away", "online", now)

        assert agent.away_time_seconds_today >= 590
        assert agent.away_time_seconds_today <= 610

    def test_no_accumulation_without_anchor(self):
        from apps.support.sat_service import sat_accumulate_time

        agent = _make_agent("Agent1", 100, status="online", last_status_change_at=None)

        now = timezone.now()
        sat_accumulate_time(agent, "online", "away", now)

        # Should set the anchor but not accumulate
        assert agent.last_status_change_at == now
        assert agent.online_time_seconds_today == 0


@pytest.mark.django_db
class TestSATReconcileLoad:
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_corrects_mismatched_count(self, mock_client_fn):
        agent = _make_agent("Agent1", 100, chats=2)
        mock_client = MagicMock()
        mock_client.count_active_tickets_by_owner.return_value = 5
        mock_client_fn.return_value = mock_client

        from apps.support.sat_service import sat_reconcile_agent_load

        result = sat_reconcile_agent_load(agent)

        assert result == 5
        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 5
        assert agent.sat_last_count_sync_at is not None

    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_returns_local_on_api_error(self, mock_client_fn):
        agent = _make_agent("Agent1", 100, chats=3)
        mock_client = MagicMock()
        mock_client.count_active_tickets_by_owner.side_effect = Exception("API error")
        mock_client_fn.return_value = mock_client

        from apps.support.sat_service import sat_reconcile_agent_load

        result = sat_reconcile_agent_load(agent)

        assert result == 3  # Local count as fallback


@pytest.mark.django_db
class TestSATResetDailyCounters:
    @patch("apps.support.sat_service.is_business_hours", return_value=False)
    def test_resets_counters_and_creates_log(self, mock_bh):
        agent = _make_agent("Agent1", 100, last_status_change_at=timezone.now() - timedelta(hours=8))
        agent.online_time_seconds_today = 14400  # 4 hours
        agent.away_time_seconds_today = 3600  # 1 hour
        agent.save()

        from apps.support.sat_service import sat_reset_daily_counters

        result = sat_reset_daily_counters()

        assert result["agents_reset"] >= 1

        agent.refresh_from_db()
        assert agent.online_time_seconds_today == 0
        assert agent.away_time_seconds_today == 0

        # Daily log should exist for yesterday
        yesterday = timezone.localdate() - timedelta(days=1)
        log = AgentDailyTimeLog.objects.filter(agent=agent, log_date=yesterday).first()
        assert log is not None
        assert log.online_time_seconds > 0


# ---------------------------------------------------------------------------
# Matchmaker Service Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMatchmakerAssignNext:
    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load", create=True)
    @patch("apps.support.durable_assignment_service.get_hubspot_client")
    def test_assigns_oldest_ticket_to_best_agent(self, mock_client_fn, mock_reconcile):
        agent = _make_agent("Agent1", 100, chats=0)
        _make_pending_ticket("T001", minutes_ago=10)
        _make_pending_ticket("T002", minutes_ago=5)  # newer, should not be picked first

        mock_reconcile.return_value = 0  # Agent has 0 chats
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        from apps.support.matchmaker_service import matchmaker_assign_next

        result = matchmaker_assign_next()

        assert result.value == "assigned"
        assert not NewConversation.objects.filter(hubspot_ticket_id="T001").exists()
        assert NewConversation.objects.filter(hubspot_ticket_id="T002").exists()

        assigned = AssignedConversation.objects.get(hubspot_ticket_id="T001")
        assert assigned.agent == agent
        assert assigned.queue_wait_seconds is not None

        # Assignment log should exist
        log = AssignmentLog.objects.filter(ticket_id="T001").first()
        assert log is not None
        assert log.agent == agent

    def test_returns_false_when_queue_empty(self):
        from apps.support.matchmaker_service import matchmaker_assign_next

        result = matchmaker_assign_next()
        assert result.value == "queue_empty"

    def test_returns_false_when_no_agents(self):
        _make_pending_ticket("T001")
        _make_agent("Away", 100, status="away")

        from apps.support.matchmaker_service import matchmaker_assign_next

        result = matchmaker_assign_next()
        assert result.value == "no_agent"

        # Ticket should be marked as queued
        conv = NewConversation.objects.get(hubspot_ticket_id="T001")
        assert conv.queue_status == "queued"
        assert conv.assignment_attempts == 1


@pytest.mark.django_db
class TestMatchmakerDrainQueue:
    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load", create=True)
    @patch("apps.support.durable_assignment_service.get_hubspot_client")
    def test_assigns_multiple_tickets(self, mock_client_fn, mock_reconcile):
        _make_agent("Agent1", 100, chats=0, max_chats=5)
        _make_agent("Agent2", 200, chats=0, max_chats=5)
        _make_pending_ticket("T001", minutes_ago=10)
        _make_pending_ticket("T002", minutes_ago=5)

        mock_reconcile.return_value = 0
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        from apps.support.matchmaker_service import matchmaker_drain_queue

        result = matchmaker_drain_queue()

        assert result["assigned"] == 2
        assert result["remaining"] == 0
        assert NewConversation.objects.count() == 0

    def test_returns_zero_when_empty(self):
        from apps.support.matchmaker_service import matchmaker_drain_queue

        result = matchmaker_drain_queue()
        assert result["assigned"] == 0
        assert result["total_pending"] == 0

    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load", create=True)
    @patch("apps.support.durable_assignment_service.get_hubspot_client")
    def test_quarantines_stale_head_and_assigns_next_ticket(self, mock_client_fn, mock_reconcile):
        from apps.integrations.hubspot.exceptions import HubSpotResourceNotFoundError
        from apps.support.matchmaker_service import matchmaker_drain_queue

        _make_agent("Agent1", 100, chats=0, max_chats=5)
        _make_pending_ticket("STALE", minutes_ago=10)
        _make_pending_ticket("VALID", minutes_ago=5)
        mock_reconcile.return_value = 0
        mock_client = MagicMock()
        mock_client.assign_ticket_owner.side_effect = [
            HubSpotResourceNotFoundError("ticket", "STALE"),
            {"id": "VALID", "owner_id": 100},
        ]
        mock_client_fn.return_value = mock_client

        result = matchmaker_drain_queue()

        assert result["assigned"] == 1
        assert result["remaining"] == 0
        assert result["total_pending"] == 2
        assert result["quarantined"] == 1
        assert result["deferred"] == 0
        assert result["processed"] == 2
        assert result["converged"] == 0
        assert result["systemic_failures"] == 0
        stale = NewConversation.objects.get(hubspot_ticket_id="STALE")
        assert stale.queue_status == NewConversation.QueueStatus.FAILED
        assert stale.failure_code == "hubspot_ticket_not_found"
        assert stale.assignment_attempts == 1
        assert not NewConversation.objects.filter(hubspot_ticket_id="VALID").exists()

    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load", create=True)
    @patch("apps.support.durable_assignment_service.get_hubspot_client")
    def test_defers_transient_provider_failure_with_backoff(self, mock_client_fn, mock_reconcile):
        from apps.integrations.hubspot.exceptions import HubSpotAPIError
        from apps.support.matchmaker_service import matchmaker_drain_queue

        _make_agent("Agent1", 100, chats=0, max_chats=5)
        _make_pending_ticket("RETRY", minutes_ago=10)
        mock_reconcile.return_value = 0
        mock_client = MagicMock()
        mock_client.assign_ticket_owner.side_effect = HubSpotAPIError(
            "temporary outage",
            external_status=503,
            retryable=True,
        )
        mock_client_fn.return_value = mock_client

        result = matchmaker_drain_queue()

        assert result["assigned"] == 0
        assert result["deferred"] == 1
        retry = NewConversation.objects.get(hubspot_ticket_id="RETRY")
        assert retry.queue_status == NewConversation.QueueStatus.QUEUED
        assert retry.failure_code == "hubspot_http_503"
        assert retry.assignment_attempts == 1
        assert retry.next_assignment_attempt_at is not None
        assert retry.next_assignment_attempt_at > timezone.now()


@pytest.mark.django_db
class TestEnqueueNewTicket:
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_creates_new_conversation(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client.get_ticket_details.return_value = {
            "id": "T001",
            "pipeline": "636459134",
            "owner_id": "",
            "subject": "Test ticket",
            "contact_name": "John",
            "contact_email": "john@test.com",
            "priority": "HIGH",
            "entered_novo_at": "1711900000000",
        }
        mock_client_fn.return_value = mock_client

        from apps.support.matchmaker_service import enqueue_new_ticket

        result = enqueue_new_ticket("T001")

        assert result is not None
        assert result.hubspot_ticket_id == "T001"
        assert NewConversation.objects.count() == 1

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_skips_ticket_with_owner(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client.get_ticket_details.return_value = {
            "id": "T001",
            "pipeline": "636459134",
            "owner_id": "12345",
        }
        mock_client_fn.return_value = mock_client

        from apps.support.matchmaker_service import enqueue_new_ticket

        result = enqueue_new_ticket("T001")

        assert result is None
        assert NewConversation.objects.count() == 0

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_idempotent_enqueue(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client.get_ticket_details.return_value = {
            "id": "T001",
            "pipeline": "636459134",
            "owner_id": "",
            "subject": "Test",
            "entered_novo_at": "1711900000000",
        }
        mock_client_fn.return_value = mock_client

        from apps.support.matchmaker_service import enqueue_new_ticket

        enqueue_new_ticket("T001")
        enqueue_new_ticket("T001")  # Second call should not duplicate

        assert NewConversation.objects.count() == 1

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_reactivates_quarantined_ticket_when_hubspot_sends_it_again(self, mock_client_fn):
        conversation = _make_pending_ticket("T001")
        conversation.queue_status = NewConversation.QueueStatus.FAILED
        conversation.assignment_attempts = 3
        conversation.next_assignment_attempt_at = timezone.now()
        conversation.failure_code = "hubspot_ticket_not_found"
        conversation.failure_message = "stale"
        conversation.save()
        mock_client_fn.return_value.get_ticket_details.return_value = {
            "id": "T001",
            "pipeline": "636459134",
            "owner_id": "",
            "entered_novo_at": "1711900000000",
        }

        from apps.support.matchmaker_service import enqueue_new_ticket

        result = enqueue_new_ticket("T001")

        assert result is not None
        result.refresh_from_db()
        assert result.queue_status == NewConversation.QueueStatus.PENDING
        assert result.assignment_attempts == 0
        assert result.next_assignment_attempt_at is None
        assert result.failure_code == ""
        assert result.failure_message == ""

    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_does_not_reactivate_predeploy_suppressed_ticket(self, mock_client_fn):
        conversation = _make_pending_ticket("T001")
        conversation.queue_status = NewConversation.QueueStatus.FAILED
        conversation.failure_code = "predeploy_queue_cleared"
        conversation.save(update_fields=["queue_status", "failure_code", "updated_at"])
        mock_client_fn.return_value.get_ticket_details.return_value = {
            "id": "T001",
            "pipeline": "636459134",
            "owner_id": "",
            "entered_novo_at": "1711900000000",
        }

        from apps.support.matchmaker_service import enqueue_new_ticket

        result = enqueue_new_ticket("T001")

        assert result is not None
        result.refresh_from_db()
        assert result.queue_status == NewConversation.QueueStatus.FAILED
        assert result.failure_code == "predeploy_queue_cleared"


# ---------------------------------------------------------------------------
# Webhook Handler Tests (async dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWebhookHandlerAsync:
    @patch("apps.webhooks.handlers.hubspot_handler.transaction.on_commit", side_effect=lambda callback: callback())
    @patch("apps.support.tasks.task_matchmaker_assign_single.delay")
    def test_novo_handler_dispatches_task(self, mock_delay, _mock_on_commit):
        from apps.webhooks.handlers.hubspot_handler import _handle_ticket_entered_novo

        _handle_ticket_entered_novo("T001", "1711900000000")

        mock_delay.assert_called_once_with("T001", "1711900000000", "")

    @patch("apps.support.tasks.task_handle_ticket_closed.delay")
    def test_closed_handler_dispatches_task(self, mock_delay):
        from apps.webhooks.handlers.hubspot_handler import _handle_ticket_entered_closed

        _handle_ticket_entered_closed("T001", "1711900000000", {"hubspot_owner_id": "123"})

        mock_delay.assert_called_once_with("T001", "1711900000000", "123")

    @patch("apps.support.tasks.task_handle_owner_change.delay")
    def test_owner_change_handler_dispatches_task(self, mock_delay):
        from apps.webhooks.handlers.hubspot_handler import _handle_ticket_owner_change

        payload = {"previousValue": "100", "sourceId": "100"}
        _handle_ticket_owner_change("T001", "200", payload)

        mock_delay.assert_called_once_with("T001", "200", payload)
