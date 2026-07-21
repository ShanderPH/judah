"""Regression tests for authoritative, absence-safe agent eligibility."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.support.models import (
    Agent,
    AgentAvailabilityDecision,
    AvailabilityReconciliationLease,
    NewConversation,
)


def _agent(*, status: str = "away") -> Agent:
    return Agent.objects.create(
        name="Nathan Test",
        agent_email="nathan.test@example.com",
        hubspot_owner_id=88093732,
        status_enum=status,
        auto_assign_enabled=True,
        is_active=True,
        current_simultaneous_chats=0,
        max_simultaneous_chats=10,
    )


def _hubspot_user(*, availability: str = "available", out_of_office: list[dict] | None = None) -> dict:
    return {
        "user_id": "207838823235",
        "email": "nathan.test@example.com",
        "availability_status": availability,
        "out_of_office_hours": json.dumps(out_of_office or []),
        "working_hours": json.dumps([{"days": "EVERY_DAY", "startMinute": 0, "endMinute": 1440}]),
        "timezone": "America/Sao_Paulo",
    }


@pytest.mark.django_db
class TestRuntimeAuthorityFence:
    @override_settings(ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_staging_cannot_write_shared_availability(self, mock_client_fn: MagicMock) -> None:
        agent = _agent(status="away")

        with patch.dict(
            os.environ,
            {"DJANGO_ENV": "staging", "RAILWAY_ENVIRONMENT_NAME": "staging"},
            clear=False,
        ):
            from apps.support.sat_service import sat_heartbeat

            result = sat_heartbeat(task_id="staging-task")

        assert result["skipped_non_authoritative_runtime"] is True
        mock_client_fn.assert_not_called()
        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert agent.availability_revision == 0

    def test_non_owner_cannot_release_lease(self) -> None:
        from apps.support.sat_service import (
            _acquire_reconciliation_lease,
            _release_reconciliation_lease,
        )

        lease = _acquire_reconciliation_lease()
        assert lease is not None
        token, _ = lease
        AvailabilityReconciliationLease.objects.filter(key="sat-authoritative-reconciliation").update(
            owner_token="replacement-owner"
        )

        assert _release_reconciliation_lease(token) is False
        AvailabilityReconciliationLease.objects.all().delete()


@pytest.mark.django_db
class TestAuthoritativeReconciliation:
    @override_settings(
        ABSENCE_SAFE_ELIGIBILITY_SHADOW=True,
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=False,
    )
    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_shadow_records_absence_without_changing_legacy_routing(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent(status="online")
        now = timezone.now()
        mock_client_fn.return_value.get_all_owners_availability.return_value = [
            _hubspot_user(
                out_of_office=[
                    {
                        "startTimestamp": (now - timedelta(hours=1)).isoformat(),
                        "endTimestamp": (now + timedelta(hours=1)).isoformat(),
                    }
                ]
            )
        ]

        from apps.support.sat_service import sat_heartbeat

        sat_heartbeat(task_id="shadow")
        agent.refresh_from_db()

        assert agent.status_enum == "online"
        assert agent.eligibility_state == "ineligible"
        assert agent.eligibility_reason == "active_out_of_office"

    @override_settings(
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
        AVAILABILITY_REQUIRED_SAMPLES=2,
        AVAILABILITY_STABLE_SECONDS=30,
    )
    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_active_out_of_office_wins_over_available(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent()
        now = timezone.now()
        mock_client_fn.return_value.get_all_owners_availability.return_value = [
            _hubspot_user(
                out_of_office=[
                    {
                        "startTimestamp": (now - timedelta(hours=1)).isoformat(),
                        "endTimestamp": (now + timedelta(hours=1)).isoformat(),
                    }
                ]
            )
        ]

        from apps.support.sat_service import sat_heartbeat

        result = sat_heartbeat(task_id="production-heartbeat")

        assert result["status_changes"] == 0
        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert agent.eligibility_state == "ineligible"
        assert agent.eligibility_reason == "active_out_of_office"
        assert agent.hubspot_user_id == "207838823235"
        decision = AgentAvailabilityDecision.objects.get(agent=agent)
        assert decision.writer_id
        assert decision.raw_state_hash
        assert decision.task_id == "production-heartbeat"

    @override_settings(
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
        AVAILABILITY_REQUIRED_SAMPLES=2,
        AVAILABILITY_STABLE_SECONDS=30,
    )
    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_available_requires_stability_then_returns_online(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent()
        mock_client_fn.return_value.get_all_owners_availability.return_value = [_hubspot_user()]

        from apps.support.sat_service import sat_heartbeat

        first = sat_heartbeat(task_id="sample-1")
        agent.refresh_from_db()
        assert first["agents_came_online"] == 0
        assert agent.status_enum == "away"
        assert agent.eligibility_reason == "stabilizing"

        Agent.objects.filter(pk=agent.pk).update(
            availability_online_since=timezone.now() - timedelta(seconds=31),
            availability_sample_count=1,
        )
        second = sat_heartbeat(task_id="sample-2")
        agent.refresh_from_db()

        assert second["agents_came_online"] == 1
        assert agent.status_enum == "online"
        assert agent.eligibility_state == "eligible"
        assert agent.eligibility_reason == "eligible"

    @override_settings(
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
        AVAILABILITY_REQUIRED_SAMPLES=2,
        AVAILABILITY_STABLE_SECONDS=30,
    )
    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_missing_remote_status_fails_closed(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent(status="online")
        mock_client_fn.return_value.get_all_owners_availability.return_value = [_hubspot_user(availability="")]

        from apps.support.sat_service import sat_heartbeat

        sat_heartbeat(task_id="missing-status")
        agent.refresh_from_db()

        assert agent.status_enum == "away"
        assert agent.eligibility_state == "ineligible"
        assert agent.eligibility_reason == "unknown_remote_status"

    @override_settings(
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
        AVAILABILITY_REQUIRED_SAMPLES=1,
        AVAILABILITY_STABLE_SECONDS=0,
    )
    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_local_schedule_is_authoritative_when_remote_schedule_is_missing(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent()
        remote_user = _hubspot_user()
        remote_user["working_hours"] = None
        remote_user["timezone"] = ""
        mock_client_fn.return_value.get_all_owners_availability.return_value = [remote_user]

        from apps.support.sat_service import sat_heartbeat

        sat_heartbeat(task_id="local-schedule")
        agent.refresh_from_db()

        assert agent.status_enum == "online"
        assert agent.eligibility_state == "eligible"
        assert agent.eligibility_reason == "eligible"
        assert agent.hubspot_user_id == "207838823235"
        assert agent.remote_working_hours == []
        assert agent.remote_timezone == ""

    @override_settings(
        ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
        AVAILABILITY_REQUIRED_SAMPLES=1,
        AVAILABILITY_STABLE_SECONDS=0,
    )
    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_heartbeat_does_not_rewrite_assignment_timestamp(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent()
        assigned_at = timezone.now() - timedelta(days=1)
        Agent.objects.filter(pk=agent.pk).update(last_assignment_at=assigned_at)
        mock_client_fn.return_value.get_all_owners_availability.return_value = [_hubspot_user()]

        original_save = Agent.save
        observed_update_fields: list[set[str] | None] = []

        def save_with_capture(instance: Agent, *args, **kwargs) -> None:
            update_fields = kwargs.get("update_fields")
            observed_update_fields.append(set(update_fields) if update_fields is not None else None)
            original_save(instance, *args, **kwargs)

        from apps.support.sat_service import sat_heartbeat

        with patch.object(Agent, "save", new=save_with_capture):
            sat_heartbeat(task_id="preserve-assignment-clock")

        agent.refresh_from_db()
        assert agent.last_assignment_at == assigned_at
        assert observed_update_fields
        assert all(fields is not None for fields in observed_update_fields)
        assert all("last_assignment_at" not in fields for fields in observed_update_fields if fields is not None)

    @patch("apps.support.sat_service.is_business_hours", return_value=False)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_heartbeat_skips_outside_local_schedule(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent(status="online")

        from apps.support.sat_service import sat_heartbeat

        result = sat_heartbeat(task_id="outside-local-schedule")
        agent.refresh_from_db()

        assert result["skipped_off_hours"] is True
        assert agent.status_enum == "online"
        mock_client_fn.assert_not_called()


@pytest.mark.django_db
class TestAssignmentFinalGuard:
    @override_settings(ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True)
    def test_manual_status_edit_cannot_create_eligibility(self) -> None:
        agent = _agent(status="online")
        agent.hubspot_user_id = "207838823235"
        agent.availability_observed_at = timezone.now()
        agent.eligibility_state = "ineligible"
        agent.eligibility_reason = "active_out_of_office"
        agent.save()

        from apps.support.queue_service import get_eligible_agents

        assert get_eligible_agents() == []

    @override_settings(ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True)
    @patch("apps.support.queue_service.get_ranked_eligible_agents")
    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load", return_value=0, create=True)
    @patch("apps.support.matchmaker_service.get_hubspot_client")
    def test_final_guard_rejects_agent_changed_after_selection(
        self,
        mock_client_fn: MagicMock,
        _mock_reconcile: MagicMock,
        mock_select: MagicMock,
    ) -> None:
        agent = _agent(status="online")
        agent.hubspot_user_id = "207838823235"
        agent.availability_observed_at = timezone.now()
        agent.eligibility_state = "ineligible"
        agent.eligibility_reason = "active_out_of_office"
        agent.save()
        mock_select.return_value = [agent]
        NewConversation.objects.create(
            hubspot_ticket_id="ABSENCE-RACE",
            entered_queue_at=timezone.now(),
            automatic_assignment_eligible=True,
        )

        from apps.support.matchmaker_service import matchmaker_assign_next

        outcome = matchmaker_assign_next()

        assert outcome.value == "no_agent"
        mock_client_fn.return_value.assign_ticket_owner.assert_not_called()
        assert NewConversation.objects.filter(hubspot_ticket_id="ABSENCE-RACE").exists()

    @override_settings(ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True)
    @patch("apps.support.queue_service.get_ranked_eligible_agents")
    @patch("apps.support.matchmaker_service.sat_reconcile_agent_load", return_value=0, create=True)
    @patch("apps.support.sat_service.sat_verify_agent_assignment_eligibility")
    @patch("apps.support.durable_assignment_service.get_hubspot_client")
    def test_remote_away_vetoes_assignment_after_candidate_selection(
        self,
        mock_client_fn: MagicMock,
        mock_remote_verify: MagicMock,
        _mock_reconcile: MagicMock,
        mock_select: MagicMock,
    ) -> None:
        from apps.support.eligibility_service import (
            EligibilityDecision,
            EligibilityReason,
        )

        agent = _agent(status="online")
        agent.hubspot_user_id = "207838823235"
        agent.availability_observed_at = timezone.now()
        agent.eligibility_state = "eligible"
        agent.eligibility_reason = "eligible"
        agent.save()
        mock_select.return_value = [agent]
        mock_remote_verify.return_value = EligibilityDecision(
            False,
            EligibilityReason.REMOTE_AWAY,
        )
        NewConversation.objects.create(
            hubspot_ticket_id="REMOTE-AWAY-RACE",
            entered_queue_at=timezone.now(),
            automatic_assignment_eligible=True,
        )

        from apps.support.matchmaker_service import matchmaker_assign_next

        outcome = matchmaker_assign_next()

        assert outcome.value == "no_agent"
        mock_remote_verify.assert_called_once()
        assert mock_remote_verify.call_args.args == (agent,)
        mock_client_fn.return_value.assign_ticket_owner.assert_not_called()
        assert NewConversation.objects.filter(hubspot_ticket_id="REMOTE-AWAY-RACE").exists()


@pytest.mark.django_db
class TestAssignmentTimeHubSpotVerification:
    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_available_response_without_remote_schedule_is_idempotently_eligible(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent(status="online")
        agent.hubspot_user_id = "207838823235"
        agent.save(update_fields=["hubspot_user_id", "updated_at"])
        initial_revision = agent.availability_revision
        mock_client_fn.return_value.get_user_by_id.return_value = {
            "id": "207838823235",
            "email": "nathan@example.com",
            "hs_availability_status": "available",
            "hs_out_of_office_hours": "[]",
            "hs_working_hours": None,
            "hs_standard_time_zone": "",
        }

        from apps.support.sat_service import (
            sat_verify_agent_assignment_eligibility,
        )

        first = sat_verify_agent_assignment_eligibility(agent)
        second = sat_verify_agent_assignment_eligibility(agent)
        agent.refresh_from_db()

        assert first == second
        assert first.eligible is True
        assert agent.availability_revision == initial_revision
        assert mock_client_fn.return_value.get_user_by_id.call_count == 2

    @patch("apps.support.sat_service.is_business_hours", return_value=False)
    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_local_schedule_vetoes_remote_available_status(
        self,
        mock_client_fn: MagicMock,
        _mock_business_hours: MagicMock,
    ) -> None:
        agent = _agent(status="online")
        agent.hubspot_user_id = "207838823235"
        agent.save(update_fields=["hubspot_user_id", "updated_at"])
        mock_client_fn.return_value.get_user_by_id.return_value = {
            "id": "207838823235",
            "email": "nathan@example.com",
            "hs_availability_status": "available",
            "hs_out_of_office_hours": "[]",
            "hs_working_hours": None,
            "hs_standard_time_zone": "",
        }

        from apps.support.sat_service import (
            sat_verify_agent_assignment_eligibility,
        )

        decision = sat_verify_agent_assignment_eligibility(agent)

        assert decision.eligible is False
        assert decision.reason.value == "outside_working_hours"

    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_away_response_fails_closed(
        self,
        mock_client_fn: MagicMock,
    ) -> None:
        agent = _agent(status="online")
        agent.hubspot_user_id = "207838823235"
        agent.save(update_fields=["hubspot_user_id", "updated_at"])
        mock_client_fn.return_value.get_user_by_id.return_value = {
            "id": "207838823235",
            "email": "nathan@example.com",
            "hs_availability_status": "away",
            "hs_out_of_office_hours": "[]",
            "hs_working_hours": ('[{"days":"EVERY_DAY","startMinute":0,"endMinute":1440}]'),
            "hs_standard_time_zone": "UTC",
        }

        from apps.support.sat_service import (
            sat_verify_agent_assignment_eligibility,
        )

        decision = sat_verify_agent_assignment_eligibility(agent)

        assert decision.eligible is False
        assert decision.reason.value == "remote_away"

    @patch("apps.integrations.hubspot.client.get_hubspot_client")
    def test_api_failure_or_missing_user_fails_closed(
        self,
        mock_client_fn: MagicMock,
    ) -> None:
        agent = _agent(status="online")
        agent.hubspot_user_id = "207838823235"
        agent.save(update_fields=["hubspot_user_id", "updated_at"])
        mock_client_fn.return_value.get_user_by_id.return_value = {}

        from apps.support.sat_service import (
            sat_verify_agent_assignment_eligibility,
        )

        decision = sat_verify_agent_assignment_eligibility(agent)

        assert decision.eligible is False
        assert decision.reason.value == "missing_observation"
