"""Regressions required by the HubSpot provider contract migration."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.apps import apps
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.integrations.hubspot.exceptions import HubSpotAPIError
from apps.integrations.hubspot.platform_contract import HubSpotCapability, check_hubspot_capabilities
from apps.integrations.hubspot.team_roster import TeamMember, TeamRosterProvider
from apps.integrations.hubspot.webhook_config import compare_app_config, compare_webhook_config
from apps.support.admin_api import _force_reassign_internal
from apps.support.agent_message_evidence import attributed_agent_cycles
from apps.support.assignment_provenance import AssignmentProvenance, administrative_source, classify_owner_effect
from apps.support.auto_assign_service import sync_hubspot_team_to_agents
from apps.support.lifecycle_occurrence_service import (
    InvalidOccurrenceEvidenceError,
    open_from_proven_occurrence,
    owner_occurrence_matches_cycle,
    record_pending_close,
    record_proven_occurrence,
)
from apps.support.models import (
    Agent,
    AgentMetrics,
    AssignedConversation,
    AssignmentLog,
    ClosedConversation,
    ConversationReassignment,
    QueuePerformanceMetrics,
    SupportConversationCycle,
    SupportLifecycleOccurrence,
    SupportTicketOccupancy,
)
from apps.support.owner_reconciliation_service import reconcile_ticket
from apps.support.provider_readiness import (
    CAPABILITY_CACHE_KEY,
    WEBHOOK_CONFIG_CACHE_KEY,
    provider_assignment_allowed,
    provider_contract_checks,
    provider_contract_reasons,
)
from apps.support.schemas import AssignedConversationResponse, ConversationReassignmentResponse
from apps.support.tasks import (
    task_aggregate_agent_metrics,
    task_aggregate_queue_metrics,
    task_handle_owner_change,
    task_reconcile_lifecycle_occurrence,
    task_scan_lifecycle_occurrences,
)
from apps.webhooks.handlers.hubspot_handler import _handle_pipeline_stage_change
from apps.webhooks.models import WebhookEvent
from common.exceptions import ExternalServiceError, ValidationError


def test_team_membership_uses_paginated_team_contract() -> None:
    """The team roster must include a member after the first page."""
    transport = Mock()
    transport.get_json.side_effect = [
        {"results": [{"userId": "1", "type": "DEFAULT"}], "paging": {"next": {"after": "next"}}},
        {"results": [{"userId": "2", "type": "EXTRA"}]},
        {"results": [{"userId": 1, "id": "101"}, {"userId": 2, "id": "102"}]},
        {"id": "1", "email": "one@example.test"},
        {"id": "2", "email": "two@example.test"},
    ]
    roster = TeamRosterProvider(transport).fetch("8")
    assert roster.complete is True
    assert {member.user_id for member in roster.members} == {"1", "2"}
    assert {member.owner_id for member in roster.members} == {101, 102}
    assert roster.pages_read == 2
    assert transport.get_json.call_args_list[1].kwargs["params"]["after"] == "next"


def test_team_sync_propagates_provider_failure() -> None:
    """A failed provider read cannot be reported as zero new agents."""
    with patch("apps.support.auto_assign_service.get_hubspot_client") as provider:
        provider.return_value.get_team_roster.side_effect = ExternalServiceError("HubSpot", "offline")
        with pytest.raises(ExternalServiceError):
            sync_hubspot_team_to_agents("8")


def test_team_roster_page_budget_stays_partial() -> None:
    """A page limit must leave an unfinished roster explicitly partial."""
    transport = Mock()
    transport.get_json.return_value = {"results": [], "paging": {"next": {"after": "next"}}}
    roster = TeamRosterProvider(transport).fetch("8", max_pages=1)
    assert roster.complete is False
    assert roster.next_cursor == "next"


def test_owner_resolution_reads_all_current_owner_pages() -> None:
    """Owner resolution must follow every provider cursor."""
    transport = Mock()
    transport.get_json.side_effect = [
        {"results": [{"userId": 1, "id": "101"}], "paging": {"next": {"after": "next"}}},
        {"results": [{"userId": 2, "id": "102"}]},
    ]
    owner_ids = TeamRosterProvider(transport)._load_owner_ids(max_pages=2)
    assert owner_ids == {"1": 101, "2": 102}
    assert transport.get_json.call_args_list[1].kwargs["params"]["after"] == "next"
    assert transport.get_json.call_args_list[0].args[0] == "/crm/owners/2026-09"


def test_incomplete_owner_resolution_never_completes_roster() -> None:
    """An exhausted owner page budget must fail roster completion."""
    transport = Mock()
    transport.get_json.side_effect = [
        {"results": [{"userId": "1"}]},
        {"results": [{"userId": 1, "id": "101"}], "paging": {"next": {"after": "next"}}},
    ]
    with pytest.raises(HubSpotAPIError, match="Owner page budget exhausted"):
        TeamRosterProvider(transport).fetch("8", max_pages=1)


@pytest.mark.parametrize("member_count", [0, 1, 100, 101])
def test_team_roster_boundary_sizes_are_complete(member_count: int) -> None:
    """Roster pagination must handle empty and full boundary pages."""
    transport = Mock()
    identifiers = [str(index) for index in range(1, member_count + 1)]
    pages = [identifiers[index : index + 100] for index in range(0, member_count, 100)] or [[]]
    transport.get_json.side_effect = [
        {
            "results": [{"userId": identity} for identity in page],
            "paging": {"next": {"after": str(index + 1)}} if index + 1 < len(pages) else {},
        }
        for index, page in enumerate(pages)
    ]
    with (
        patch.object(TeamRosterProvider, "_load_owner_ids", return_value={}),
        patch.object(
            TeamRosterProvider,
            "_resolve_member",
            side_effect=lambda user_id, member_type, _owners: TeamMember(user_id, member_type, "active", int(user_id)),
        ),
    ):
        roster = TeamRosterProvider(transport).fetch("8")
    assert roster.complete is True
    assert len(roster.members) == member_count
    assert roster.pages_read == len(pages)


def test_capability_preflight_keeps_auth_failures_distinct() -> None:
    """Capability checks must distinguish missing access from unavailable endpoints."""
    transport = Mock()

    def read(path: str, **_kwargs):
        """Simulate capability-specific authorization responses."""
        if "teams" in path:
            raise HubSpotAPIError("forbidden", external_status=403, retryable=False)
        if "users" in path:
            raise HubSpotAPIError("unauthorized", external_status=401, retryable=False)
        return {"results": []}

    transport.get_json.side_effect = read
    results = {result.capability: result for result in check_hubspot_capabilities(transport, team_id="8")}
    assert results[HubSpotCapability.TEAMS_MEMBERSHIP].outcome == "forbidden"
    assert results[HubSpotCapability.USERS_READ].outcome == "unauthorized"
    assert results[HubSpotCapability.TICKETS_WRITE].outcome == "unverified"


@pytest.mark.parametrize("status, expected", [(429, "rate_limited"), (503, "server_error")])
def test_capability_preflight_classifies_retryable_provider_failures(status, expected) -> None:
    """Retryable provider statuses must retain their distinct outcomes."""
    transport = Mock()
    transport.get_json.side_effect = HubSpotAPIError("failed", external_status=status)
    results = check_hubspot_capabilities(transport)
    assert results[0].outcome == expected


def test_provider_readiness_blocks_unverified_write_and_stale_roster(settings) -> None:
    """Enforcement must reject unverified writes and an expired roster."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.HUBSPOT_N1_TEAM_ID = "8"
    now = timezone.now()
    cache.set(
        CAPABILITY_CACHE_KEY,
        {
            "checked_at": now.isoformat(),
            "outcomes": {
                "tickets_read": "available",
                "tickets_write": "unverified",
                "owners_read": "available",
                "teams_membership": "available",
                "users_read": "available",
            },
        },
        timeout=900,
    )
    cache.delete("hubspot_roster_complete_at:8")
    checks = provider_contract_checks(now)
    assert checks["mandatory_capabilities_available"] is False
    assert checks["roster_fresh"] is False
    assert set(provider_contract_reasons(checks)) >= {"hubspot_capabilities_unavailable", "hubspot_roster_stale"}
    assert provider_assignment_allowed() is False


def test_published_webhook_readback_controls_enforce_gate(settings, tmp_path) -> None:
    """Published webhook evidence must control the enforcement gate."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_N1_TEAM_ID = "8"
    now = timezone.now().isoformat()
    cache.set(
        CAPABILITY_CACHE_KEY,
        {
            "checked_at": now,
            "outcomes": {
                "tickets_read": "available",
                "tickets_write": "verified_in_sandbox",
                "owners_read": "available",
                "teams_membership": "available",
                "users_read": "available",
            },
        },
        timeout=900,
    )
    cache.set("hubspot_roster_complete_at:8", now, timeout=86400)
    cache.delete(WEBHOOK_CONFIG_CACHE_KEY)
    assert provider_assignment_allowed() is False

    desired_webhooks = settings.BASE_DIR / "hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json"
    desired_app = settings.BASE_DIR / "hubspot-app/src/app/app-hsmeta.json"
    published_webhooks = tmp_path / "published-webhooks.json"
    published_app = tmp_path / "published-app.json"
    published_webhooks.write_text(desired_webhooks.read_text(encoding="utf-8"), encoding="utf-8")
    published_app.write_text(desired_app.read_text(encoding="utf-8"), encoding="utf-8")
    call_command(
        "record_hubspot_webhook_readback",
        published_webhooks=published_webhooks,
        published_app=published_app,
    )
    assert provider_assignment_allowed() is True
    settings.SUPPORT_CAPACITY_MODE = "off"
    assert provider_assignment_allowed() is False
    assert "canonical_capacity_writer_inactive" in provider_contract_reasons(provider_contract_checks())


def test_webhook_governance_detects_missing_required_subscription() -> None:
    """Missing required subscriptions must block webhook readiness."""
    desired = {
        "uid": "judah_webhooks",
        "config": {
            "settings": {"targetUrl": "https://example.test/hubspot", "maxConcurrentRequests": 10},
            "subscriptions": {
                "legacyCrmObjects": [
                    {"subscriptionType": "ticket.propertyChange", "propertyName": "hubspot_owner_id", "active": True}
                ]
            },
        },
    }
    published = {
        "uid": "judah_webhooks",
        "config": {
            "settings": {"targetUrl": "https://example.test/hubspot", "maxConcurrentRequests": 10},
            "subscriptions": {"legacyCrmObjects": []},
        },
    }
    result = compare_webhook_config(desired, published)
    assert result["ready"] is False
    assert result["missing_active_subscriptions"] == ["ticket.propertyChange:hubspot_owner_id"]


def test_webhook_governance_accepts_non_property_subscription_without_property_name() -> None:
    """Extra creation subscriptions must not require a property name."""
    desired = {
        "uid": "judah_webhooks",
        "config": {
            "settings": {"targetUrl": "https://example.test/hubspot", "maxConcurrentRequests": 10},
            "subscriptions": {
                "legacyCrmObjects": [
                    {"subscriptionType": "ticket.propertyChange", "propertyName": "hubspot_owner_id", "active": True},
                ]
            },
        },
    }
    published = {
        "uid": "judah_webhooks",
        "config": {
            "settings": {"targetUrl": "https://example.test/hubspot", "maxConcurrentRequests": 10},
            "subscriptions": {
                "legacyCrmObjects": [
                    {"subscriptionType": "ticket.propertyChange", "propertyName": "hubspot_owner_id", "active": True},
                    {"subscriptionType": "ticket.creation", "active": True},
                ]
            },
        },
    }
    assert compare_webhook_config(desired, published)["ready"] is True


def test_webhook_governance_requires_property_name_for_property_change() -> None:
    """Property-change subscriptions must declare the changed property."""
    document = {
        "uid": "judah_webhooks",
        "config": {
            "subscriptions": {
                "legacyCrmObjects": [
                    {"subscriptionType": "ticket.propertyChange", "active": True},
                ]
            }
        },
    }
    with pytest.raises(ValueError, match="propertyName"):
        compare_webhook_config(document, document)


def test_app_governance_detects_scope_drift() -> None:
    """Published app scopes must match the required scope set."""
    desired = {"uid": "judah_app", "config": {"auth": {"requiredScopes": ["tickets", "settings.users.read"]}}}
    published = {"uid": "judah_app", "config": {"auth": {"requiredScopes": ["tickets"]}}}
    result = compare_app_config(desired, published)
    assert result["ready"] is False
    assert result["missing_required_scopes"] == ["settings.users.read"]


def test_owner_effect_needs_evidence_to_be_called_manual() -> None:
    """Owner provenance must identify manual effects only with evidence."""
    assert classify_owner_effect() == AssignmentProvenance.UNKNOWN_EXTERNAL
    assert classify_owner_effect(attempt_type="manual") == AssignmentProvenance.MANUAL_ASSIGNMENT
    assert classify_owner_effect(attempt_type="automatic") == AssignmentProvenance.AUTOMATIC_ASSIGNMENT
    assert administrative_source("capacity", reserved=True) == "forced_reassignment:reserved:capacity"


def test_proven_occurrence_requires_account_and_ticket_identity() -> None:
    """Proven lifecycle evidence must include both tenant and ticket identity."""
    with pytest.raises(InvalidOccurrenceEvidenceError, match="account and ticket"):
        record_proven_occurrence(
            account_id="",
            ticket_id="123",
            occurrence_type=SupportLifecycleOccurrence.Type.CLOSED,
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
            evidence_source="crm_readback",
        )


def test_administrative_owner_effect_blocks_without_provider_proof() -> None:
    """Administrative owner changes must stop when provider proof is absent."""
    target = Agent(hubspot_owner_id=700, name="Agent")
    with (
        patch("apps.support.availability_runtime.require_routing_writer_authority"),
        patch("apps.support.provider_readiness.provider_assignment_allowed", return_value=False),
        patch("apps.support.admin_api._hubspot_assign") as owner_patch,
        pytest.raises(ValidationError, match="provider contract is unavailable"),
    ):
        _force_reassign_internal("123", target)
    owner_patch.assert_not_called()


def test_occurrence_table_has_postgres_runtime_guard() -> None:
    """PostgreSQL must reject lifecycle rows that violate evidence constraints."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL runtime guard")
    with connection.cursor() as cursor:
        cursor.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'support_lifecycle_occurrences'")
        assert cursor.fetchone() == (True,)
        cursor.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_guard_support_lifecycle_occurrences_runtime'"
        )
        assert cursor.fetchone() == (1,)


def test_stage_change_receipt_time_is_not_cycle_identity(settings) -> None:
    """A stage notification has no proven stage-entry timestamp of its own."""
    with patch("apps.webhooks.handlers.hubspot_handler._handle_ticket_entered_novo") as dispatch:
        _handle_pipeline_stage_change(
            "close-ticket", settings.HUBSPOT_SUPPORT_NEW_STAGE_ID, {"occurredAt": 1788224400000}
        )
    dispatch.assert_called_once_with("close-ticket", None)


def test_close_without_materialized_time_is_persisted_pending(settings) -> None:
    """Provider lag must keep occupancy and the cycle active for a later readback."""
    settings.SUPPORT_CAPACITY_MODE = "shadow"
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "shadow"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    opened_at = datetime(2026, 9, 1, tzinfo=UTC)
    cycle = SupportConversationCycle.objects.create(
        cycle_key="provider-contract:close-ticket",
        source_account_id="test-portal",
        hubspot_ticket_id="close-ticket",
        entered_stage_at=opened_at,
        opened_at=opened_at,
        state=SupportConversationCycle.State.ASSIGNED,
    )
    agent = Agent.objects.create(hubspot_owner_id=700, name="Agent", agent_email="agent@example.test")
    AssignedConversation.objects.create(
        hubspot_ticket_id="close-ticket", cycle=cycle, agent=agent, hubspot_owner_id=700, assigned_at=opened_at
    )
    occupancy = SupportTicketOccupancy.objects.create(
        source_account_id="test-portal",
        hubspot_ticket_id="close-ticket",
        cycle=cycle,
        agent=agent,
        hubspot_owner_id=700,
        state="active",
    )
    snapshot = {
        "id": "close-ticket",
        "pipeline": settings.HUBSPOT_SUPPORT_PIPELINE_ID,
        "stage": settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID,
        "owner_id": "700",
        "entered_closed_at": None,
        "updated_at": "2026-09-01T01:00:00Z",
    }
    reconcile_ticket("close-ticket", provider_data=snapshot)
    occurrence_model = apps.get_model("support", "SupportLifecycleOccurrence")
    occupancy.refresh_from_db()
    cycle.refresh_from_db()
    assert occupancy.state == "active"
    assert cycle.state == SupportConversationCycle.State.ASSIGNED
    assert occurrence_model.objects.filter(
        hubspot_ticket_id="close-ticket", evidence_status="provider_materialization_pending"
    ).exists()


def test_owner_before_proven_entry_keeps_lifecycle_uninvented(settings) -> None:
    """An owner snapshot must not invent a cycle before proven entry."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    Agent.objects.create(hubspot_owner_id=702, name="Agent", agent_email="agent3@example.test")
    snapshot = {
        "id": "owner-before-cycle",
        "pipeline": settings.HUBSPOT_SUPPORT_PIPELINE_ID,
        "stage": settings.HUBSPOT_SUPPORT_NEW_STAGE_ID,
        "owner_id": "702",
        "entered_novo_at": None,
        "updated_at": "2026-09-01T01:00:00Z",
    }
    occupancy = reconcile_ticket("owner-before-cycle", provider_data=snapshot)
    assert occupancy.state == "active"
    assert occupancy.cycle_id is None
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id="owner-before-cycle").exists()
    assert not AssignedConversation.objects.filter(hubspot_ticket_id="owner-before-cycle").exists()

    snapshot["entered_novo_at"] = datetime(2026, 9, 1, tzinfo=UTC)
    snapshot["updated_at"] = "2026-09-01T01:01:00Z"
    occupancy = reconcile_ticket("owner-before-cycle", provider_data=snapshot)
    assert occupancy.cycle_id is not None
    assert SupportConversationCycle.objects.filter(hubspot_ticket_id="owner-before-cycle").count() == 1
    assigned = AssignedConversation.objects.get(hubspot_ticket_id="owner-before-cycle")
    assert assigned.assigned_at is None
    assert AssignedConversationResponse.model_validate(assigned).assigned_at is None
    assert assigned.queue_wait_seconds is None
    assert AssignmentLog.objects.get(ticket_id="owner-before-cycle").assignment_type == "unknown_external"
    assert (
        SupportLifecycleOccurrence.objects.filter(
            hubspot_ticket_id="owner-before-cycle",
            occurrence_type="entered_support_queue",
            evidence_status="proven",
            processing_status="processed",
        ).count()
        == 1
    )


def test_owner_webhook_waits_for_cycle_then_projects_proven_occurrence(settings) -> None:
    """A proven owner event must wait until its cycle exists."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    Agent.objects.create(hubspot_owner_id=705, name="Owner", agent_email="owner@example.test")
    snapshot = {
        "id": "7050",
        "pipeline": settings.HUBSPOT_SUPPORT_PIPELINE_ID,
        "stage": settings.HUBSPOT_SUPPORT_NEW_STAGE_ID,
        "owner_id": "705",
        "entered_novo_at": None,
        "updated_at": "2026-09-01T01:00:00Z",
    }
    with (
        patch("apps.support.availability_runtime.may_write_routing_state", return_value=True),
        patch("apps.integrations.hubspot.client.get_hubspot_client") as provider,
    ):
        provider.return_value.get_ticket_details.return_value = snapshot
        task_handle_owner_change("7050", "705", {"eventId": "evt-7050", "occurredAt": 1788224400000})
    occurrence = SupportLifecycleOccurrence.objects.get(
        hubspot_ticket_id="7050", occurrence_type=SupportLifecycleOccurrence.Type.OWNER_CHANGED
    )
    assert occurrence.evidence_status == SupportLifecycleOccurrence.EvidenceStatus.PROVEN
    assert occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.PENDING
    assert occurrence.next_reconcile_at is not None
    assert SupportTicketOccupancy.objects.get(hubspot_ticket_id="7050").hubspot_owner_id == 705
    assert not AssignedConversation.objects.filter(hubspot_ticket_id="7050").exists()

    snapshot["entered_novo_at"] = datetime(2026, 9, 1, tzinfo=UTC)
    snapshot["updated_at"] = "2026-09-01T01:01:00Z"
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(
        next_reconcile_at=timezone.now() - timedelta(seconds=1)
    )
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot
        assert task_reconcile_lifecycle_occurrence(str(occurrence.pk)) == "processed"
    occurrence.refresh_from_db()
    assert occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.PROCESSED
    assert AssignedConversation.objects.get(hubspot_ticket_id="7050").assigned_at is None


def test_stale_owner_occurrence_cannot_claim_new_cycle(settings) -> None:
    """An older owner event must not attach to a later cycle."""
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    entered_at = datetime(2026, 9, 2, tzinfo=UTC)
    opened = open_from_proven_occurrence(
        ticket_id="stale-owner",
        entered_at=entered_at,
        account_id="test-portal",
        evidence_source="webhook_property",
    )
    assert opened.cycle is not None
    old_owner = record_proven_occurrence(
        account_id="test-portal",
        ticket_id="stale-owner",
        occurrence_type=SupportLifecycleOccurrence.Type.OWNER_CHANGED,
        occurred_at=entered_at - timedelta(minutes=1),
        evidence_source="webhook_property",
    )
    assert owner_occurrence_matches_cycle(old_owner, opened.cycle.pk) is False


def test_owner_retry_keeps_proven_evidence_on_capability_failure(settings) -> None:
    """A failed provider retry must retain proven owner evidence."""
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    occurrence = record_proven_occurrence(
        account_id="test-portal",
        ticket_id="owner-capability",
        occurrence_type=SupportLifecycleOccurrence.Type.OWNER_CHANGED,
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        evidence_source="webhook_property",
    )
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.side_effect = HubSpotAPIError(
            "forbidden", external_status=403, retryable=False
        )
        assert task_reconcile_lifecycle_occurrence(str(occurrence.pk)) == "repair_required"
    occurrence.refresh_from_db()
    assert occurrence.evidence_status == SupportLifecycleOccurrence.EvidenceStatus.PROVEN
    assert occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.REPAIR_REQUIRED
    assert occurrence.next_reconcile_at is None


def test_enforce_queue_metrics_count_reopened_ticket_by_cycle(settings) -> None:
    """Queue metrics must count reopened ticket cycles separately."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    agent = Agent.objects.create(
        hubspot_owner_id=713, hubspot_user_id="713", name="Metrics", agent_email="metrics@example.test"
    )
    transfer_agent = Agent.objects.create(hubspot_owner_id=714, name="Transfer", agent_email="transfer@example.test")
    yesterday = timezone.localdate() - timedelta(days=1)
    entered_at = timezone.make_aware(datetime.combine(yesterday, time(12)))
    first = SupportConversationCycle.objects.create(
        cycle_key="metrics:reopen:first",
        source_account_id="test-portal",
        hubspot_ticket_id="reopened-metrics",
        entered_stage_at=entered_at,
        opened_at=entered_at,
        state=SupportConversationCycle.State.CLOSED,
        closed_at=entered_at + timedelta(hours=2),
    )
    second = SupportConversationCycle.objects.create(
        cycle_key="metrics:reopen:second",
        source_account_id="test-portal",
        hubspot_ticket_id="reopened-metrics",
        entered_stage_at=entered_at + timedelta(hours=3),
        opened_at=entered_at + timedelta(hours=3),
        state=SupportConversationCycle.State.ASSIGNED,
    )
    ClosedConversation.objects.create(
        hubspot_ticket_id="reopened-metrics",
        cycle=first,
        agent=transfer_agent,
        hubspot_owner_id=714,
        assigned_at=entered_at + timedelta(minutes=1),
        closed_at=entered_at + timedelta(hours=2),
        queue_wait_seconds=Decimal("60.00"),
    )
    ConversationReassignment.objects.create(
        hubspot_ticket_id="reopened-metrics",
        cycle=first,
        from_agent=agent,
        from_hubspot_owner_id=713,
        to_agent=transfer_agent,
        to_hubspot_owner_id=714,
        reassigned_at=entered_at + timedelta(hours=1),
    )
    AssignedConversation.objects.create(
        hubspot_ticket_id="reopened-metrics",
        cycle=second,
        agent=agent,
        hubspot_owner_id=713,
        assigned_at=entered_at + timedelta(hours=3, minutes=2),
        queue_wait_seconds=Decimal("120.00"),
    )
    for assigned_agent, assignment_type in (
        (agent, "automatic_assignment"),
        (transfer_agent, "forced_reassignment"),
    ):
        log = AssignmentLog.objects.create(
            ticket_id="reopened-metrics",
            cycle=first,
            agent=assigned_agent,
            agent_name=assigned_agent.name,
            hubspot_owner_id=assigned_agent.hubspot_owner_id,
            assignment_type=assignment_type,
        )
        AssignmentLog.objects.filter(pk=log.pk).update(assigned_at=entered_at + timedelta(minutes=1))

    task_aggregate_queue_metrics()

    metrics = QueuePerformanceMetrics.objects.get(metric_date=yesterday)
    assert metrics.total_entered_queue == 2
    assert metrics.total_assigned == 2
    assert metrics.total_closed == 1
    assert metrics.avg_queue_wait_seconds == Decimal("90.00")
    assert metrics.assignments_by_agent == {"713": 1, "714": 1}
    task_aggregate_agent_metrics()
    assert AgentMetrics.objects.get(agent_id=713).total_chats == 1

    for message_id, actor_id, occurred_at in (
        ("wrong-agent", "A-714", entered_at + timedelta(minutes=30)),
        ("after-transfer", "A-713", entered_at + timedelta(minutes=90)),
    ):
        WebhookEvent.objects.create(
            source="hubspot",
            event_type="conversation.newMessage",
            event_id=message_id,
            object_id="thread-1",
            portal_id="test-portal",
            hubspot_ticket_id="reopened-metrics",
            occurred_at=occurred_at,
            ignored_reason="outgoing_message",
            payload={"_agent_message_evidence": {"actor_id": actor_id}},
        )
    task_aggregate_queue_metrics()
    assert QueuePerformanceMetrics.objects.get(metric_date=yesterday).assignments_by_agent == {"713": 1, "714": 1}
    WebhookEvent.objects.create(
        source="hubspot",
        event_type="conversation.newMessage",
        event_id="message-by-source",
        object_id="thread-1",
        portal_id="test-portal",
        hubspot_ticket_id="reopened-metrics",
        occurred_at=entered_at + timedelta(minutes=30),
        ignored_reason="outgoing_message",
        payload={"_agent_message_evidence": {"actor_id": "A-713"}},
    )
    task_aggregate_queue_metrics()
    task_aggregate_agent_metrics()
    metrics.refresh_from_db()
    assert metrics.assignments_by_agent == {"713": 2, "714": 1}
    assert AgentMetrics.objects.get(agent_id=713).total_chats == 2


def test_intermediate_owner_counts_only_after_sending_during_tenure() -> None:
    """Transfer attribution must require a message during each owner tenure."""
    agents = [
        Agent.objects.create(
            hubspot_owner_id=owner_id,
            hubspot_user_id=str(owner_id),
            name=f"Agent {owner_id}",
            agent_email=f"agent{owner_id}@example.test",
        )
        for owner_id in (801, 802, 803)
    ]
    opened_at = timezone.now() - timedelta(days=1)
    cycle = SupportConversationCycle.objects.create(
        cycle_key="metrics:multi-hop",
        source_account_id="test-portal",
        hubspot_ticket_id="multi-hop",
        entered_stage_at=opened_at,
        opened_at=opened_at,
        state=SupportConversationCycle.State.CLOSED,
        closed_at=opened_at + timedelta(hours=2),
    )
    initial = AssignmentLog.objects.create(
        ticket_id="multi-hop", cycle=cycle, agent=agents[0], agent_name=agents[0].name, hubspot_owner_id=801
    )
    AssignmentLog.objects.filter(pk=initial.pk).update(assigned_at=opened_at + timedelta(minutes=1))
    for index, transfer_minute in enumerate((30, 60)):
        ConversationReassignment.objects.create(
            hubspot_ticket_id="multi-hop",
            cycle=cycle,
            from_agent=agents[index],
            from_hubspot_owner_id=agents[index].hubspot_owner_id,
            to_agent=agents[index + 1],
            to_hubspot_owner_id=agents[index + 1].hubspot_owner_id,
            reassigned_at=opened_at + timedelta(minutes=transfer_minute),
        )
    ClosedConversation.objects.create(
        hubspot_ticket_id="multi-hop",
        cycle=cycle,
        agent=agents[2],
        hubspot_owner_id=803,
        closed_at=opened_at + timedelta(hours=2),
    )
    for owner_id, minute in ((801, 15), (802, 75)):
        WebhookEvent.objects.create(
            source="hubspot",
            event_type="conversation.newMessage",
            event_id=f"message-{owner_id}",
            object_id="thread-multi-hop",
            portal_id="test-portal",
            hubspot_ticket_id="multi-hop",
            occurred_at=opened_at + timedelta(minutes=minute),
            ignored_reason="outgoing_message",
            payload={"_agent_message_evidence": {"actor_id": f"A-{owner_id}"}},
        )
    assert attributed_agent_cycles({cycle.pk}) == {(cycle.pk, 801), (cycle.pk, 803)}

    WebhookEvent.objects.create(
        source="hubspot",
        event_type="conversation.newMessage",
        event_id="message-802-during-tenure",
        object_id="thread-multi-hop",
        portal_id="test-portal",
        hubspot_ticket_id="multi-hop",
        occurred_at=opened_at + timedelta(minutes=45),
        ignored_reason="outgoing_message",
        payload={"_agent_message_evidence": {"actor_id": "A-802"}},
    )
    with CaptureQueriesContext(connection) as queries:
        assert attributed_agent_cycles({cycle.pk}) == {(cycle.pk, 801), (cycle.pk, 802), (cycle.pk, 803)}
    assert sum('FROM "webhook_events"' in query["sql"] for query in queries) == 1


def test_readiness_counts_only_pending_closes(settings) -> None:
    """Readiness close lag must ignore pending events of other types."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_AGE_SECONDS = 3600
    now = timezone.now()
    SupportLifecycleOccurrence.objects.create(
        source_account_id="test-portal",
        hubspot_ticket_id="owner-only",
        occurrence_type=SupportLifecycleOccurrence.Type.OWNER_CHANGED,
        evidence_status=SupportLifecycleOccurrence.EvidenceStatus.PROVIDER_MATERIALIZATION_PENDING,
        evidence_source="provider_observation",
        evidence_key="owner-only:pending",
    )
    close = SupportLifecycleOccurrence.objects.create(
        source_account_id="test-portal",
        hubspot_ticket_id="close-pending",
        occurrence_type=SupportLifecycleOccurrence.Type.CLOSED,
        evidence_status=SupportLifecycleOccurrence.EvidenceStatus.PROVIDER_MATERIALIZATION_PENDING,
        evidence_source="provider_observation",
        evidence_key="close-pending:pending",
    )
    SupportLifecycleOccurrence.objects.filter(hubspot_ticket_id="owner-only").update(
        created_at=now - timedelta(hours=2)
    )
    checks = provider_contract_checks(now)
    assert checks["pending_close_count"] == 1
    assert "lifecycle_close_materialization_stale" not in provider_contract_reasons(checks)
    SupportLifecycleOccurrence.objects.filter(pk=close.pk).update(created_at=now - timedelta(hours=2))
    checks = provider_contract_checks(now)
    assert "lifecycle_close_materialization_stale" in provider_contract_reasons(checks)


def test_owner_snapshot_without_event_time_keeps_transfer_time_unknown(settings) -> None:
    """Owner snapshots must not invent a transfer timestamp."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    original = Agent.objects.create(hubspot_owner_id=711, name="Original", agent_email="original@example.test")
    replacement = Agent.objects.create(hubspot_owner_id=712, name="Replacement", agent_email="replacement@example.test")
    entered_at = datetime(2026, 9, 1, tzinfo=UTC)
    opened = open_from_proven_occurrence(
        ticket_id="7110",
        entered_at=entered_at,
        account_id="test-portal",
        evidence_source="webhook_property",
    )
    cycle = opened.cycle
    assert cycle is not None
    cycle.state = SupportConversationCycle.State.ASSIGNED
    cycle.save(update_fields=["state"])
    AssignedConversation.objects.create(
        hubspot_ticket_id="7110",
        cycle=cycle,
        agent=original,
        hubspot_owner_id=711,
        assigned_at=entered_at,
    )
    SupportTicketOccupancy.objects.create(
        source_account_id="test-portal",
        hubspot_ticket_id="7110",
        cycle=cycle,
        agent=original,
        hubspot_owner_id=711,
        state="active",
    )
    reconcile_ticket(
        "7110",
        provider_data={
            "id": "7110",
            "pipeline": settings.HUBSPOT_SUPPORT_PIPELINE_ID,
            "stage": settings.HUBSPOT_SUPPORT_NEW_STAGE_ID,
            "owner_id": "712",
            "entered_novo_at": entered_at,
            "updated_at": "2026-09-01T01:00:00Z",
        },
    )
    assigned = AssignedConversation.objects.get(hubspot_ticket_id="7110")
    reassignment = ConversationReassignment.objects.get(hubspot_ticket_id="7110")
    assert assigned.agent_id == replacement.pk
    assert reassignment.reassigned_at is None
    assert ConversationReassignmentResponse.model_validate(reassignment).reassigned_at is None


def test_pending_close_converges_once_after_provider_materializes_time(settings) -> None:
    """A pending close must converge exactly once after provider readback."""
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    settings.SUPPORT_CAPACITY_MODE = "shadow"
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "shadow"
    opened_at = datetime(2026, 9, 1, tzinfo=UTC)
    closed_at = opened_at + timedelta(hours=1)
    cycle = SupportConversationCycle.objects.create(
        cycle_key="provider-contract:reconcile-ticket",
        source_account_id="test-portal",
        hubspot_ticket_id="reconcile-ticket",
        entered_stage_at=opened_at,
        opened_at=opened_at,
        state=SupportConversationCycle.State.ASSIGNED,
    )
    agent = Agent.objects.create(hubspot_owner_id=701, name="Agent", agent_email="agent2@example.test")
    AssignedConversation.objects.create(
        hubspot_ticket_id="reconcile-ticket", cycle=cycle, agent=agent, hubspot_owner_id=701, assigned_at=opened_at
    )
    SupportTicketOccupancy.objects.create(
        source_account_id="test-portal",
        hubspot_ticket_id="reconcile-ticket",
        cycle=cycle,
        agent=agent,
        hubspot_owner_id=701,
        state="active",
    )
    pending = record_pending_close(
        account_id="test-portal",
        ticket_id="reconcile-ticket",
        cycle_id=cycle.pk,
        provider_updated_at=None,
        schedule=False,
    )
    SupportLifecycleOccurrence.objects.filter(pk=pending.pk).update(
        next_reconcile_at=timezone.now() - timedelta(seconds=1)
    )
    snapshot = {
        "id": "reconcile-ticket",
        "pipeline": settings.HUBSPOT_SUPPORT_PIPELINE_ID,
        "stage": settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID,
        "owner_id": "701",
        "entered_closed_at": closed_at,
        "updated_at": closed_at.isoformat(),
    }
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot
        assert task_reconcile_lifecycle_occurrence.run(str(pending.pk)) == "processed"
        assert task_reconcile_lifecycle_occurrence.run(str(pending.pk)) == "processed"
    pending.refresh_from_db()
    cycle.refresh_from_db()
    assert pending.evidence_status == "proven"
    assert pending.processing_status == "processed"
    assert pending.occurred_at == closed_at
    assert cycle.state == SupportConversationCycle.State.CLOSED
    assert ClosedConversation.objects.filter(cycle=cycle).count() == 1


def test_pending_close_exhausts_bounded_budget_without_time(settings) -> None:
    """Missing close time must eventually require repair after its retry budget."""
    settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_ATTEMPTS = 1
    pending = record_pending_close(
        account_id="test-portal",
        ticket_id="never-materializes",
        cycle_id=None,
        provider_updated_at=None,
        schedule=False,
    )
    SupportLifecycleOccurrence.objects.filter(pk=pending.pk).update(
        next_reconcile_at=timezone.now() - timedelta(seconds=1)
    )
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = {"entered_closed_at": None}
        assert task_reconcile_lifecycle_occurrence.run(str(pending.pk)) == "repair_required"
    pending.refresh_from_db()
    assert pending.evidence_status == "ambiguous"
    assert pending.processing_status == "repair_required"
    assert pending.occurred_at is None


@pytest.mark.parametrize("status", [401, 403])
def test_pending_close_capability_failure_needs_repair(settings, status: int) -> None:
    """A capability failure must mark pending close evidence for repair."""
    pending = record_pending_close(
        account_id="test-portal",
        ticket_id=f"missing-scope-{status}",
        cycle_id=None,
        provider_updated_at=None,
        schedule=False,
    )
    SupportLifecycleOccurrence.objects.filter(pk=pending.pk).update(
        next_reconcile_at=timezone.now() - timedelta(seconds=1)
    )
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.side_effect = HubSpotAPIError(
            "scope missing", external_status=status, retryable=False
        )
        assert task_reconcile_lifecycle_occurrence.run(str(pending.pk)) == "repair_required"
    pending.refresh_from_db()
    assert pending.last_error_code == "provider_capability_failure"
    assert pending.processing_status == "repair_required"


def test_lost_lifecycle_callback_is_recovered_by_due_scan() -> None:
    """The due scan must recover a lost lifecycle task callback."""
    pending = record_pending_close(
        account_id="test-portal", ticket_id="scan-pending", cycle_id=None, provider_updated_at=None, schedule=False
    )
    SupportLifecycleOccurrence.objects.filter(pk=pending.pk).update(
        next_reconcile_at=timezone.now() - timedelta(seconds=1)
    )
    with patch("apps.support.tasks.task_reconcile_lifecycle_occurrence.delay") as dispatch:
        assert task_scan_lifecycle_occurrences.run() == 1
    dispatch.assert_called_once_with(str(pending.pk))
