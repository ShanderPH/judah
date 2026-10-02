"""Regression coverage for durable, configuration-bound HubSpot evidence."""

from __future__ import annotations

import json
import os
import time
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.support.availability_runtime import assignment_gate_rejection_reason, may_assign
from apps.support.matchmaker_service import matchmaker_drain_queue, process_queue_item
from apps.support.models import NewConversation
from apps.support.provider_readiness import (
    CAPABILITY_CACHE_KEY,
    provider_assignment_allowed,
    provider_assignment_rejection_reason,
    provider_contract_checks,
    provider_contract_reasons,
)
from apps.support.webhook_proof import (
    WEBHOOK_CONFIG_CACHE_KEY,
    configuration_fingerprint,
    evaluate_webhook_proof,
    expected_configuration_fingerprint,
    load_desired_configuration,
    record_published_configuration,
)


@pytest.fixture
def provider_evidence(settings):
    """Enable enforce with valid capability/roster and a fresh versioned proof."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_N1_TEAM_ID = "8"
    settings.AUTO_ASSIGNMENT_ENABLED = True
    settings.AUTO_ASSIGNMENT_CANARY_AGENT_IDS = ()
    settings.ABSENCE_SAFE_ELIGIBILITY_SHADOW = False
    settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED = True
    cache.clear()
    now = timezone.now()
    cache.set(
        CAPABILITY_CACHE_KEY,
        {
            "checked_at": now.isoformat(),
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
    cache.set("hubspot_roster_complete_at:8", now.isoformat(), timeout=900)
    proof = record_published_configuration(*load_desired_configuration())
    yield proof
    cache.clear()


@pytest.mark.parametrize("hours, stale", [(0, False), (24, False), (25, True), (2400, True)])
def test_proof_validity_does_not_expire(provider_evidence, hours, stale) -> None:
    now = timezone.now()
    provider_evidence["checked_at"] = (now - timedelta(hours=hours)).isoformat()
    cache.set(WEBHOOK_CONFIG_CACHE_KEY, provider_evidence, timeout=None)
    original = cache.get(WEBHOOK_CONFIG_CACHE_KEY)
    assert provider_assignment_allowed() is True
    assert may_assign() is True
    with patch("apps.support.provider_readiness.logger") as logger:
        checks = provider_contract_checks(now)
    assert checks["webhook_config_verified"] is True
    assert checks["webhook_config_status"] == "valid"
    assert checks["webhook_config_stale"] is stale
    assert checks["webhook_config_readback_age_seconds"] == hours * 3600
    assert not any("webhook" in reason for reason in provider_contract_reasons(checks))
    assert checks["warnings"] == (["hubspot_webhook_config_stale"] if stale else [])
    assert logger.warning.called is stale
    assert cache.get(WEBHOOK_CONFIG_CACHE_KEY) == original


@pytest.mark.parametrize(
    "condition, status, reason",
    [
        ("missing", "missing", "missing"),
        ("invalid", "invalid", "invalid"),
        ("mismatch", "fingerprint_mismatch", "fingerprint_mismatch"),
        ("legacy", "fingerprint_missing", "invalid"),
        ("wrong_version", "invalid", "invalid"),
        ("bad_date", "invalid", "invalid"),
        ("not_boolean", "invalid", "invalid"),
    ],
)
def test_rejected_proof_is_fail_closed_and_has_specific_reason(
    provider_evidence, condition, status, reason, monkeypatch
) -> None:
    monkeypatch.setenv("DJANGO_ENV", "production")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    if condition == "missing":
        cache.delete(WEBHOOK_CONFIG_CACHE_KEY)
    else:
        if condition == "invalid":
            provider_evidence["ready"] = False
        elif condition == "mismatch":
            provider_evidence["config_fingerprint"] = "different"
        elif condition == "legacy":
            provider_evidence.pop("config_fingerprint")
            provider_evidence.pop("schema_version")
        elif condition == "wrong_version":
            provider_evidence["schema_version"] = 2
        elif condition == "not_boolean":
            provider_evidence["ready"] = "true"
        else:
            provider_evidence["checked_at"] = "invalid"
        cache.set(WEBHOOK_CONFIG_CACHE_KEY, provider_evidence, timeout=None)
    assert provider_assignment_allowed() is False
    with patch("apps.support.availability_runtime.logger") as logger:
        assert may_assign(operation="test_proof") is False
    logger.warning.assert_called_once_with(
        "assignment_gate_rejected", operation="test_proof", reason=f"provider_webhook_proof_{reason}"
    )
    checks = provider_contract_checks()
    assert checks["webhook_config_status"] == status
    assert f"hubspot_webhook_config_{reason}" in provider_contract_reasons(checks)


def test_proof_survives_the_previous_destructive_timeout(provider_evidence) -> None:
    # Move only the cache clock; capability/roster expiry must remain independent.
    with patch("time.time", return_value=time.time() + 86401):
        assert cache.get(WEBHOOK_CONFIG_CACHE_KEY) == provider_evidence
    assert cache._expire_info[cache.make_key(WEBHOOK_CONFIG_CACHE_KEY)] is None


def test_fingerprint_is_canonical_and_binds_both_manifests() -> None:
    webhooks, app = load_desired_configuration()
    fingerprint = configuration_fingerprint(webhooks, app)
    assert len(fingerprint) == 64
    assert fingerprint == configuration_fingerprint(dict(reversed(list(webhooks.items()))), app)
    for changed in ("app", "webhooks"):
        modified = json.loads(json.dumps({"app": app, "webhooks": webhooks}))
        modified[changed]["uid"] += "_changed"
        assert configuration_fingerprint(modified["webhooks"], modified["app"]) != fingerprint


@pytest.mark.parametrize("change", ["webhooks", "app", "both", "malformed", "missing_file", "json_list"])
def test_command_invalidates_prior_proof_and_fails_on_any_bad_export(provider_evidence, tmp_path, change) -> None:
    webhooks, app = load_desired_configuration()
    if change in {"webhooks", "both"}:
        webhooks["uid"] = "wrong"
    if change in {"app", "both"}:
        app["uid"] = "wrong"
    webhook_path, app_path = tmp_path / "webhooks.json", tmp_path / "app.json"
    webhook_path.write_text(json.dumps(webhooks))
    app_path.write_text(json.dumps(app))
    if change == "malformed":
        webhook_path.write_text("broken")
    elif change == "missing_file":
        webhook_path.unlink()
    elif change == "json_list":
        webhook_path.write_text("[]")
    with pytest.raises(CommandError):
        call_command("record_hubspot_webhook_readback", published_webhooks=webhook_path, published_app=app_path)
    assert cache.get(WEBHOOK_CONFIG_CACHE_KEY)["ready"] is False
    assert provider_assignment_allowed() is False


def test_command_records_success_only_after_both_exports_match(provider_evidence, tmp_path) -> None:
    webhooks, app = load_desired_configuration()
    webhook_path, app_path = tmp_path / "webhooks.json", tmp_path / "app.json"
    webhook_path.write_text(json.dumps(webhooks))
    app_path.write_text(json.dumps(app))
    output = StringIO()
    call_command(
        "record_hubspot_webhook_readback", published_webhooks=webhook_path, published_app=app_path, stdout=output
    )
    proof = json.loads(output.getvalue())
    assert proof == cache.get(WEBHOOK_CONFIG_CACHE_KEY)
    assert proof["ready"] is True
    assert proof["config_fingerprint"] == expected_configuration_fingerprint()
    assert proof["schema_version"] == 1


@pytest.mark.parametrize("snapshot", [{}, [], "bad", {"checked_at": "2026-10-01T00:00:00"}])
def test_malformed_proof_is_invalid(snapshot) -> None:
    evaluation = evaluate_webhook_proof(snapshot, expected_fingerprint="expected", now=timezone.now())
    assert evaluation.verified is False
    assert evaluation.rejection_reason == "invalid"


def test_real_runtime_rejection_remains_distinct(provider_evidence, monkeypatch) -> None:
    monkeypatch.setenv("DJANGO_ENV", "staging")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "staging")
    with patch("apps.support.availability_runtime.logger") as logger:
        assert may_assign(operation="test_authority") is False
    assert logger.warning.call_count == 1
    assert logger.warning.call_args.args == ("runtime_authority_rejected",)
    assert logger.warning.call_args.kwargs["operation"] == "test_authority"


def test_provider_block_preserves_queue_and_never_logs_runtime_rejection(provider_evidence) -> None:
    row = NewConversation.objects.create(
        hubspot_ticket_id="proof-blocked", entered_queue_at=timezone.now(), automatic_assignment_eligible=True
    )
    cache.delete(WEBHOOK_CONFIG_CACHE_KEY)
    with (
        patch("apps.support.availability_runtime.logger") as logger,
        patch("apps.support.durable_assignment_service.reserve_next_assignment") as reserve,
        patch("apps.support.durable_assignment_service.get_hubspot_client") as provider,
    ):
        assert process_queue_item().made_progress is False
        result = matchmaker_drain_queue()
    assert result["skipped_assignment_disabled"] is True
    assert result["remaining"] == 1
    row.refresh_from_db()
    assert row.automatic_assignment_eligible is True
    reserve.assert_not_called()
    provider.assert_not_called()
    assert [call.args[0] for call in logger.warning.call_args_list] == ["assignment_gate_rejected"] * 2


def test_stale_proof_does_not_disable_matchmaker(provider_evidence) -> None:
    provider_evidence["checked_at"] = (timezone.now() - timedelta(days=2)).isoformat()
    cache.set(WEBHOOK_CONFIG_CACHE_KEY, provider_evidence, timeout=None)
    result = matchmaker_drain_queue()
    assert result["assigned"] == 0
    assert "skipped_assignment_disabled" not in result


@pytest.mark.parametrize(
    "gate, reason",
    [
        ("capabilities", "provider_capabilities_unavailable"),
        ("roster", "provider_roster_stale"),
        ("capacity", "canonical_capacity_writer_inactive"),
        ("disabled", "auto_assignment_disabled"),
        ("canary", "invalid_canary_configuration"),
        ("absence", "absence_safe_not_enforced"),
    ],
)
def test_other_gates_remain_enforced(provider_evidence, settings, gate, reason) -> None:
    if gate == "capabilities":
        cache.delete(CAPABILITY_CACHE_KEY)
    elif gate == "roster":
        cache.delete("hubspot_roster_complete_at:8")
    elif gate == "capacity":
        settings.SUPPORT_CAPACITY_MODE = "off"
    elif gate == "disabled":
        settings.AUTO_ASSIGNMENT_ENABLED = False
    elif gate == "canary":
        settings.AUTO_ASSIGNMENT_CANARY_AGENT_IDS = ("invalid",)
    else:
        settings.ABSENCE_SAFE_ELIGIBILITY_SHADOW = True
        settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED = False
    assert assignment_gate_rejection_reason() == reason
    assert may_assign() is False


def test_unreadable_desired_manifest_cannot_enable_assignment(provider_evidence, settings, tmp_path) -> None:
    settings.BASE_DIR = tmp_path
    assert provider_assignment_allowed() is False
    assert provider_assignment_rejection_reason() == "provider_evidence_unavailable"


@pytest.mark.parametrize("hours", [0, 25])
def test_real_assignment_completes_with_current_or_stale_proof(provider_evidence, settings, hours) -> None:
    """Exercise reservation, owner readback and canonical capacity with enforce."""
    from apps.support.models import Agent, AgentCapacityReservation, AssignedConversation, AssignmentAttempt
    from apps.support.tests.test_manual_assignment_capacity import agent, queue, ticket

    settings.HUBSPOT_PORTAL_ID = "test-portal"
    provider_evidence["checked_at"] = (timezone.now() - timedelta(hours=hours)).isoformat()
    cache.set(WEBHOOK_CONFIG_CACHE_KEY, provider_evidence, timeout=None)
    target = agent(200)
    Agent.objects.filter(pk=target.pk).update(
        hubspot_user_id="200",
        availability_observed_at=timezone.now(),
        eligibility_state="eligible",
        eligibility_reason="eligible",
    )
    queue()
    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client") as integrations,
        patch("apps.support.durable_assignment_service.get_hubspot_client") as assignments,
        patch("apps.support.sat_service.is_business_hours", return_value=True),
    ):
        provider = integrations.return_value
        assignments.return_value = provider
        provider.get_user_by_id.return_value = {
            "id": "200",
            "hs_availability_status": "available",
            "hs_out_of_office_hours": "[]",
        }
        provider.list_active_ticket_ids_by_owner.return_value = ((), True)
        provider.get_ticket_details.return_value = ticket("")
        provider.assign_ticket_owner.side_effect = lambda *args: setattr(
            provider.get_ticket_details, "return_value", ticket(200)
        )
        result = matchmaker_drain_queue()
    assert result["assigned"] == 1
    assert "skipped_assignment_disabled" not in result
    assert AssignedConversation.objects.get().agent_id == target.pk
    assert AssignmentAttempt.objects.get().state == "completed"
    assert AgentCapacityReservation.objects.get().state == "converted"
    assert Agent.objects.get(pk=target.pk).current_simultaneous_chats == 1
    provider.assign_ticket_owner.assert_called_once_with("cap-1", 200)


@pytest.mark.skipif(os.environ.get("JUDAH_PROOF_LOCAL_REDIS_TEST") != "1", reason="Explicit local Redis gate")
def test_real_redis_stores_proof_without_ttl(settings) -> None:
    """Confirm Redis persistence semantics using an isolated local test key."""
    from uuid import uuid4

    from django.test import override_settings
    from redis import Redis

    redis_url = "redis://127.0.0.1:6379/15"
    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": redis_url,
                "KEY_PREFIX": f"judah-webhook-proof-test-{uuid4()}",
            }
        }
    ):
        client = Redis.from_url(redis_url)
        key = cache.make_key(WEBHOOK_CONFIG_CACHE_KEY)
        try:
            proof = record_published_configuration(*load_desired_configuration())
            assert client.ttl(key) == -1
            assert cache.get(WEBHOOK_CONFIG_CACHE_KEY) == proof
        finally:
            client.delete(key)
            client.close()


@pytest.mark.parametrize("proof_state", ["missing", "stale"])
def test_pr134_entry_recovery_does_not_bypass_or_disable_assignment_gate(provider_evidence, proof_state) -> None:
    """Recovery of proven entry evidence is independent of permission to assign."""
    from apps.support.models import SupportConversationCycle, SupportLifecycleOccurrence
    from apps.support.tasks import task_reconcile_lifecycle_occurrence, task_scan_lifecycle_occurrences
    from apps.support.tests.test_lifecycle_entry_recovery import record_entry

    if proof_state == "missing":
        cache.delete(WEBHOOK_CONFIG_CACHE_KEY)
    else:
        provider_evidence["checked_at"] = (timezone.now() - timedelta(days=2)).isoformat()
        cache.set(WEBHOOK_CONFIG_CACHE_KEY, provider_evidence, timeout=None)
    occurrence = record_entry("proof-entry-recovery")
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)
    with patch("apps.support.tasks.task_reconcile_lifecycle_occurrence.delay") as dispatch:
        assert task_scan_lifecycle_occurrences.run() == 1
    dispatch.assert_called_once_with(str(occurrence.pk))
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "processed"
    provider.assert_not_called()
    assert SupportConversationCycle.objects.get(hubspot_ticket_id="proof-entry-recovery").state == "queued"
    occurrence.refresh_from_db()
    assert occurrence.retry_count == 1
    assert occurrence.processing_status == "processed"
    assert may_assign() is (proof_state == "stale")
