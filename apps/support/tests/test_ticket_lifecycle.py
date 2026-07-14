"""Tests for ticket lifecycle — closure, owner-change, and count management.

Covers the critical path for current_simultaneous_chats accuracy:
  - handle_ticket_closed: atomic decrement, correct target, idempotency
  - task_handle_owner_change: idempotency guard on retries
  - matchmaker _do_assign: retry-agent reconciliation
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.support.models import (
    Agent,
    AssignedConversation,
    ClosedConversation,
    ConversationReassignment,
    NewConversation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(name: str, owner_id: int, chats: int = 0, max_chats: int = 5, status: str = "online") -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower().replace(' ', '.')}@test.com",
        hubspot_owner_id=owner_id,
        status_enum=status,
        current_simultaneous_chats=chats,
        max_simultaneous_chats=max_chats,
        auto_assign_enabled=True,
        is_active=True,
    )


def _make_assigned(ticket_id: str, agent: Agent, minutes_ago: int = 10) -> AssignedConversation:
    return AssignedConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        agent=agent,
        hubspot_owner_id=agent.hubspot_owner_id,
        agent_name=agent.name,
        pipeline_id="636459134",
        assigned_at=timezone.now() - timedelta(minutes=minutes_ago),
        entered_queue_at=timezone.now() - timedelta(minutes=minutes_ago + 5),
    )


# ---------------------------------------------------------------------------
# handle_ticket_closed — atomic decrement and correct target
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHandleTicketClosed:
    def test_decrements_assigned_agent_not_closing_agent(self):
        """Always decrement the assigned agent, not whoever closed the ticket."""
        assigned_agent = _make_agent("AssignedAgent", owner_id=100, chats=2)
        closing_agent = _make_agent("ClosingAgent", owner_id=200, chats=1)
        _make_assigned("T001", assigned_agent)

        from apps.support.auto_assign_service import handle_ticket_closed

        handle_ticket_closed("T001", owner_id=str(closing_agent.hubspot_owner_id))

        assigned_agent.refresh_from_db()
        closing_agent.refresh_from_db()

        # Assigned agent's count should drop
        assert assigned_agent.current_simultaneous_chats == 1
        # Closing agent's count must NOT change
        assert closing_agent.current_simultaneous_chats == 1

    def test_ticket_moved_to_closed_conversations(self):
        agent = _make_agent("Agent", owner_id=100, chats=1)
        _make_assigned("T002", agent)

        from apps.support.auto_assign_service import handle_ticket_closed

        handle_ticket_closed("T002", closed_at_ms="1711900000000")

        assert not AssignedConversation.objects.filter(hubspot_ticket_id="T002").exists()
        closed = ClosedConversation.objects.filter(hubspot_ticket_id="T002").first()
        assert closed is not None
        assert closed.agent == agent

    def test_idempotent_double_call_does_not_double_decrement(self):
        """Second call with the same ticket should be skipped via Redis dedup lock."""
        agent = _make_agent("Agent", owner_id=100, chats=3)
        _make_assigned("T003", agent)

        from apps.support.auto_assign_service import handle_ticket_closed

        # First call should process normally
        handle_ticket_closed("T003")
        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 2  # decremented once

        # Second call — ticket is gone (no AssignedConversation), dedup lock already
        # cleared. Even without the lock, the DoesNotExist path should not decrement.
        handle_ticket_closed("T003")
        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 2  # unchanged

    def test_concurrent_closure_via_dedup_lock(self):
        """Simulates the race condition where both hs_v2_date_entered_939275052
        and hs_pipeline_stage webhooks fire concurrently for the same ticket.
        The Redis dedup lock should cause the second call to skip entirely."""
        from django.core.cache import cache

        agent = _make_agent("Agent", owner_id=100, chats=2)
        _make_assigned("T004", agent)

        lock_key = "ticket_close:T004"

        # Simulate: first call holds the lock (already claimed)
        cache.add(lock_key, "1", timeout=60)

        from apps.support.auto_assign_service import handle_ticket_closed

        # This call should be skipped because the lock is already held
        handle_ticket_closed("T004")

        agent.refresh_from_db()
        # Count must NOT be decremented while the lock is held by another process
        assert agent.current_simultaneous_chats == 2

        # Clean up
        cache.delete(lock_key)

    def test_pending_ticket_deleted_on_close(self):
        """If a ticket is still in new_conversations when closed, it must be removed."""
        NewConversation.objects.create(
            hubspot_ticket_id="T005",
            pipeline_id="636459134",
            entered_queue_at=timezone.now() - timedelta(minutes=2),
        )

        from apps.support.auto_assign_service import handle_ticket_closed

        handle_ticket_closed("T005")

        assert not NewConversation.objects.filter(hubspot_ticket_id="T005").exists()
        closed = ClosedConversation.objects.filter(hubspot_ticket_id="T005").first()
        assert closed is not None  # minimal record still created

    def test_closed_without_assigned_record_creates_minimal_record(self):
        """Ticket closed before ever being assigned: create a minimal ClosedConversation."""
        from apps.support.auto_assign_service import handle_ticket_closed

        handle_ticket_closed("T_NEVER_ASSIGNED", owner_id="100")

        assert ClosedConversation.objects.filter(hubspot_ticket_id="T_NEVER_ASSIGNED").exists()

    def test_count_floor_stays_at_zero(self):
        """decrement on an agent with chats=0 must not go negative."""
        agent = _make_agent("Agent", owner_id=100, chats=0)
        _make_assigned("T006", agent)

        from apps.support.auto_assign_service import handle_ticket_closed

        handle_ticket_closed("T006")

        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 0


# ---------------------------------------------------------------------------
# task_handle_owner_change — idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHandleOwnerChange:
    def test_decrements_source_increments_target(self):
        from_agent = _make_agent("FromAgent", owner_id=100, chats=2)
        to_agent = _make_agent("ToAgent", owner_id=200, chats=1)
        _make_assigned("T010", from_agent)

        from apps.support.tasks import task_handle_owner_change

        payload = {"previousValue": "100"}
        task_handle_owner_change("T010", "200", payload)

        from_agent.refresh_from_db()
        to_agent.refresh_from_db()

        assert from_agent.current_simultaneous_chats == 1  # decremented
        assert to_agent.current_simultaneous_chats == 2  # incremented

    def test_reassignment_log_created(self):
        from_agent = _make_agent("FromAgent", owner_id=100, chats=1)
        _make_agent("ToAgent", owner_id=200, chats=0)  # must exist in DB for reassignment target
        _make_assigned("T011", from_agent)

        from apps.support.tasks import task_handle_owner_change

        task_handle_owner_change("T011", "200", {"previousValue": "100"})

        log = ConversationReassignment.objects.filter(hubspot_ticket_id="T011").first()
        assert log is not None
        assert log.from_hubspot_owner_id == 100
        assert log.to_hubspot_owner_id == 200

    def test_dedup_lock_prevents_double_count_adjustment(self):
        """When the same owner-change fires twice (HubSpot retry), the Redis dedup
        lock must prevent the second run from adjusting counts again."""
        from django.core.cache import cache

        from_agent = _make_agent("FromAgent", owner_id=100, chats=2)
        to_agent = _make_agent("ToAgent", owner_id=200, chats=1)
        _make_assigned("T012", from_agent)

        # Pre-acquire the lock for this ticket+owner combo
        lock_key = "owner_change:T012:100:200"
        cache.add(lock_key, "1", timeout=120)

        from apps.support.tasks import task_handle_owner_change

        task_handle_owner_change("T012", "200", {"previousValue": "100"})

        from_agent.refresh_from_db()
        to_agent.refresh_from_db()

        # Neither should change while lock is held
        assert from_agent.current_simultaneous_chats == 2
        assert to_agent.current_simultaneous_chats == 1

        cache.delete(lock_key)

    def test_skips_when_no_previous_owner(self):
        """No previousValue means initial assignment, not a reassignment — skip."""
        agent = _make_agent("Agent", owner_id=200, chats=0)
        _make_assigned("T013", agent)

        from apps.support.tasks import task_handle_owner_change

        task_handle_owner_change("T013", "200", {"previousValue": None})

        assert ConversationReassignment.objects.filter(hubspot_ticket_id="T013").count() == 0
        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 0

    def test_skips_when_owner_unchanged(self):
        """Same previous and new owner — no-op."""
        agent = _make_agent("Agent", owner_id=100, chats=1)
        _make_assigned("T014", agent)

        from apps.support.tasks import task_handle_owner_change

        task_handle_owner_change("T014", "100", {"previousValue": "100"})

        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 1  # unchanged
        assert ConversationReassignment.objects.filter(hubspot_ticket_id="T014").count() == 0

    def test_assigned_conversation_updated_to_new_agent(self):
        from_agent = _make_agent("FromAgent", owner_id=100, chats=1)
        to_agent = _make_agent("ToAgent", owner_id=200, chats=0)
        _make_assigned("T015", from_agent)

        from apps.support.tasks import task_handle_owner_change

        task_handle_owner_change("T015", "200", {"previousValue": "100"})

        conv = AssignedConversation.objects.get(hubspot_ticket_id="T015")
        assert conv.agent == to_agent
        assert conv.hubspot_owner_id == 200
        assert conv.assignment_count == 2  # was 1, incremented


# ---------------------------------------------------------------------------
# Matchmaker: retry agent reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMatchmakerRetryReconciliation:
    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load")
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_retry_agent_reconciled_when_first_at_capacity(self, mock_client_fn, mock_reconcile):
        """When the first-selected agent is at capacity after reconcile, the retry
        agent must ALSO be reconciled before assignment.

        The 4-rule sort selects the agent with the fewest local chats first
        (owner_id=100, chats=0). Its reconcile returns 5 → at capacity.
        The retry selects owner_id=200 (chats=1) and its reconcile returns 1 → OK.
        """
        # owner_id=100 has fewer local chats → selected first by the queue algorithm
        _make_agent("FirstAgent", owner_id=100, chats=0, max_chats=5)  # exists in DB; selected then rejected
        # owner_id=200 has more local chats → selected as the retry candidate
        second_agent = _make_agent("SecondAgent", owner_id=200, chats=1, max_chats=5)

        NewConversation.objects.create(
            hubspot_ticket_id="T020",
            pipeline_id="636459134",
            entered_queue_at=timezone.now() - timedelta(minutes=5),
        )

        # FirstAgent is actually at capacity per HubSpot (5); SecondAgent is not (1).
        mock_reconcile.side_effect = lambda agent: 5 if agent.hubspot_owner_id == 100 else 1
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        from apps.support.matchmaker_service import matchmaker_assign_next

        result = matchmaker_assign_next()

        assert result is True

        # sat_reconcile_agent_load must have been called at least twice —
        # once for first_agent (rejected) and once for second_agent (accepted).
        assert mock_reconcile.call_count >= 2

        assigned = AssignedConversation.objects.get(hubspot_ticket_id="T020")
        assert assigned.agent == second_agent

    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load")
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_queued_when_retry_agent_also_at_capacity(self, mock_client_fn, mock_reconcile):
        """If both the first and retry agents are at capacity after reconcile,
        the ticket should stay queued rather than being over-assigned."""
        _make_agent("Agent1", owner_id=100, chats=4, max_chats=5)
        _make_agent("Agent2", owner_id=200, chats=4, max_chats=5)

        pending = NewConversation.objects.create(
            hubspot_ticket_id="T021",
            pipeline_id="636459134",
            entered_queue_at=timezone.now() - timedelta(minutes=5),
        )

        # Both agents at or above capacity after reconciliation
        mock_reconcile.return_value = 5
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        from apps.support.matchmaker_service import matchmaker_assign_next

        result = matchmaker_assign_next()

        assert result is False
        pending.refresh_from_db()
        assert pending.queue_status == "queued"


# ---------------------------------------------------------------------------
# _handle_pipeline_stage_change — no duplicate closure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPipelineStageChangeNoDuplicateClosure:
    @patch("apps.support.tasks.task_handle_ticket_closed.delay")
    def test_fechado_stage_change_does_not_dispatch_closure_task(self, mock_delay):
        """hs_pipeline_stage → 939275052 must NOT dispatch task_handle_ticket_closed
        since that is handled by the hs_v2_date_entered_939275052 handler."""
        from apps.webhooks.handlers.hubspot_handler import _handle_pipeline_stage_change

        _handle_pipeline_stage_change("T_STAGE", "939275052")

        mock_delay.assert_not_called()

    @patch("apps.support.tasks.task_matchmaker_assign_single.delay")
    @patch("apps.support.tasks.task_handle_ticket_closed.delay")
    def test_novo_stage_change_dispatches_assignment_not_closure(self, mock_closed, mock_assign):
        """NOVO stage transitions dispatch assignment, never closure."""
        from apps.webhooks.handlers.hubspot_handler import _handle_pipeline_stage_change

        _handle_pipeline_stage_change("T_STAGE2", "939275049")  # NOVO stage

        mock_closed.assert_not_called()
        mock_assign.assert_called_once_with("T_STAGE2", None)
