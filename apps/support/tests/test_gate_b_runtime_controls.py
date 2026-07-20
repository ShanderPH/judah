"""Gate B regression tests for queue controls and Python writer authority."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.support.models import Agent, AssignedConversation, NewConversation


def _agent(name: str, owner_id: int) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower()}@example.test",
        hubspot_owner_id=owner_id,
        status_enum=Agent.StatusEnum.ONLINE,
        auto_assign_enabled=True,
        is_active=True,
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        hubspot_user_id=f"user-{owner_id}",
        availability_observed_at=timezone.now(),
        eligibility_state=Agent.EligibilityState.ELIGIBLE,
        eligibility_reason="eligible",
    )


@pytest.mark.django_db
class TestQueueSafeControls:
    @override_settings(AUTO_ASSIGNMENT_ENABLED=False)
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    @patch("apps.support.sat_service.sat_heartbeat")
    @patch("apps.support.matchmaker_service.matchmaker_assign_next")
    def test_assignment_off_ingests_idempotently_without_owner_mutation(
        self,
        mock_assign: MagicMock,
        mock_sat: MagicMock,
        mock_client_fn: MagicMock,
    ) -> None:
        mock_client_fn.return_value.get_ticket_details.return_value = {
            "id": "GATE-B-QUEUE",
            "pipeline": "636459134",
            "owner_id": "",
        }

        from apps.support.tasks import task_matchmaker_assign_single

        assert task_matchmaker_assign_single("GATE-B-QUEUE") is False
        assert task_matchmaker_assign_single("GATE-B-QUEUE") is False

        assert NewConversation.objects.filter(hubspot_ticket_id="GATE-B-QUEUE").count() == 1
        mock_sat.assert_not_called()
        mock_assign.assert_not_called()
        mock_client_fn.return_value.assign_ticket_owner.assert_not_called()

    @override_settings(AUTO_ASSIGNMENT_ENABLED=False)
    @patch("apps.support.auto_assign_service.get_hubspot_client")
    def test_reconciliation_repairs_backlog_while_assignment_is_off(
        self,
        mock_client_fn: MagicMock,
    ) -> None:
        mock_client_fn.return_value.search_tickets_in_novo_stage.return_value = [
            {
                "id": "GATE-B-BACKLOG",
                "pipeline": "636459134",
                "owner_id": "",
            }
        ]

        from apps.support.auto_assign_service import sync_novo_stage_tickets

        first = sync_novo_stage_tickets()
        second = sync_novo_stage_tickets()

        assert first["created"] == 1
        assert second["skipped"] == 1
        assert NewConversation.objects.filter(hubspot_ticket_id="GATE-B-BACKLOG").count() == 1
        mock_client_fn.return_value.assign_ticket_owner.assert_not_called()

    @override_settings(
        AUTO_ASSIGNMENT_ENABLED=True,
        ABSENCE_SAFE_ELIGIBILITY_SHADOW=False,
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=False,
    )
    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load", return_value=0)
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_enabling_assignment_drains_preserved_backlog(
        self,
        mock_client_fn: MagicMock,
        _mock_reconcile: MagicMock,
    ) -> None:
        agent = _agent("BacklogAgent", 91001)
        NewConversation.objects.create(
            hubspot_ticket_id="GATE-B-DRAIN",
            entered_queue_at=timezone.now(),
        )

        from apps.support.matchmaker_service import matchmaker_drain_queue

        result = matchmaker_drain_queue()

        assert result["assigned"] == 1
        assert AssignedConversation.objects.get(hubspot_ticket_id="GATE-B-DRAIN").agent == agent
        mock_client_fn.return_value.assign_ticket_owner.assert_called_once_with("GATE-B-DRAIN", 91001)


@pytest.mark.django_db
class TestCanaryControls:
    @override_settings(
        AUTO_ASSIGNMENT_ENABLED=True,
        ABSENCE_SAFE_ELIGIBILITY_SHADOW=False,
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    )
    def test_canary_allowlist_filters_the_safe_candidate_pool(self) -> None:
        allowed = _agent("Allowed", 92001)
        _agent("Excluded", 92002)

        with override_settings(AUTO_ASSIGNMENT_CANARY_AGENT_IDS=(str(allowed.id),)):
            from apps.support.queue_service import get_eligible_agents

            assert [agent.id for agent in get_eligible_agents()] == [allowed.id]

    @override_settings(
        AUTO_ASSIGNMENT_ENABLED=True,
        ABSENCE_SAFE_ELIGIBILITY_SHADOW=False,
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=False,
        AUTO_ASSIGNMENT_CANARY_AGENT_IDS=("00000000-0000-0000-0000-000000000001",),
    )
    def test_canary_cannot_enable_legacy_eligibility(self) -> None:
        from apps.support.availability_runtime import may_assign

        assert may_assign() is False

    @override_settings(
        AUTO_ASSIGNMENT_ENABLED=True,
        ABSENCE_SAFE_ELIGIBILITY_SHADOW=False,
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
        AUTO_ASSIGNMENT_CANARY_AGENT_IDS=("not-a-uuid",),
    )
    def test_invalid_canary_configuration_fails_closed(self) -> None:
        from apps.support.availability_runtime import may_assign
        from apps.support.queue_service import get_eligible_agents

        _agent("InvalidCanary", 92003)
        assert may_assign() is False
        assert get_eligible_agents() == []


class TestFailClosedRuntime:
    @override_settings(
        AUTO_ASSIGNMENT_ENABLED=False,
        ABSENCE_SAFE_ELIGIBILITY_SHADOW=True,
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=False,
    )
    def test_production_without_assignment_flag_is_ingestion_only(self) -> None:
        from apps.support.availability_runtime import (
            may_assign,
            may_ingest_queue,
            may_reconcile_queue,
        )

        with patch.dict(
            os.environ,
            {"DJANGO_ENV": "production", "RAILWAY_ENVIRONMENT_NAME": "production"},
            clear=False,
        ):
            assert may_ingest_queue() is True
            assert may_reconcile_queue() is True
            assert may_assign() is False

    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    @patch("apps.support.agent_sync_service.is_business_hours", return_value=True)
    def test_count_reconciler_rejects_before_network_io(
        self,
        _mock_business_hours: MagicMock,
        mock_client_fn: MagicMock,
    ) -> None:
        from apps.support.tasks import task_reconcile_agent_counts

        with patch.dict(
            os.environ,
            {"DJANGO_ENV": "staging", "RAILWAY_ENVIRONMENT_NAME": "staging"},
            clear=False,
        ):
            result = task_reconcile_agent_counts()

        assert result["skipped_non_authoritative_runtime"] is True
        mock_client_fn.assert_not_called()


def test_writer_inventory_covers_gate_b_entrypoints() -> None:
    from apps.support.availability_runtime import ROUTING_WRITER_CAPABILITIES

    expected = {
        "enqueue_new_ticket",
        "sync_novo_stage_tickets",
        "task_reconcile_agent_counts",
        "admin_create_agent",
        "admin_manual_assign",
        "admin_force_reassign",
    }
    assert expected <= ROUTING_WRITER_CAPABILITIES.keys()
