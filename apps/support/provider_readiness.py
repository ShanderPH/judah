"""PII-free HubSpot provider contract observations for operational readiness."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count
from django.utils import timezone
from redis.exceptions import RedisError

from apps.integrations.hubspot.platform_contract import (
    HubSpotCapability,
    HubSpotTransport,
    check_hubspot_capabilities,
)
from apps.support.webhook_proof import (
    WEBHOOK_CONFIG_CACHE_KEY,
    evaluate_webhook_proof,
    expected_configuration_fingerprint,
)

logger = structlog.get_logger(__name__)

# Cache snapshots and provider probes contain JSON values without a shared schema.

CAPABILITY_CACHE_KEY = "hubspot_capabilities_snapshot"


def refresh_hubspot_capabilities() -> dict[str, str]:
    """Run read-only provider probes and cache their classified outcomes."""
    if not settings.HUBSPOT_ACCESS_TOKEN:
        outcomes = {capability.value: "unconfigured" for capability in HubSpotCapability}
    else:
        transport = HubSpotTransport(settings.HUBSPOT_ACCESS_TOKEN)
        outcomes = {
            result.capability.value: result.outcome
            for result in check_hubspot_capabilities(transport, team_id=settings.HUBSPOT_N1_TEAM_ID)
        }
        if settings.HUBSPOT_TICKETS_WRITE_VERIFIED:
            outcomes[HubSpotCapability.TICKETS_WRITE.value] = "verified_in_sandbox"
    cache.set(CAPABILITY_CACHE_KEY, {"checked_at": timezone.now().isoformat(), "outcomes": outcomes}, timeout=900)
    return outcomes


def _provider_access_checks(now: datetime) -> dict[str, Any]:
    """Read only the cached provider access signals used by hot-path gates."""
    mode = settings.HUBSPOT_PROVIDER_CONTRACT_MODE
    if mode == "off":
        return {"mode": mode}

    snapshot = cache.get(CAPABILITY_CACHE_KEY) or {}
    checked_at = datetime.fromisoformat(snapshot["checked_at"]) if snapshot.get("checked_at") else None
    capability_age = max(0, int((now - checked_at).total_seconds())) if checked_at else None
    outcomes = snapshot.get("outcomes") or {}
    required_capabilities = (
        HubSpotCapability.TICKETS_READ,
        HubSpotCapability.OWNERS_READ,
        HubSpotCapability.TEAMS_MEMBERSHIP,
        HubSpotCapability.USERS_READ,
    )
    mandatory_available = all(outcomes.get(capability.value) == "available" for capability in required_capabilities)
    mandatory_available = (
        mandatory_available and outcomes.get(HubSpotCapability.TICKETS_WRITE.value) == "verified_in_sandbox"
    )

    roster_at_raw = cache.get(f"hubspot_roster_complete_at:{settings.HUBSPOT_N1_TEAM_ID}")
    roster_at = datetime.fromisoformat(roster_at_raw) if roster_at_raw else None
    roster_age = max(0, int((now - roster_at).total_seconds())) if roster_at else None
    roster_fresh = roster_age is not None and roster_age <= settings.HUBSPOT_ROSTER_MAX_AGE_SECONDS
    webhook_proof = evaluate_webhook_proof(
        cache.get(WEBHOOK_CONFIG_CACHE_KEY), expected_fingerprint=expected_configuration_fingerprint(), now=now
    )

    return {
        "mode": mode,
        "canonical_capacity_writer": settings.SUPPORT_CAPACITY_MODE == "enforce",
        "capability_outcomes": outcomes,
        "capability_age_seconds": capability_age,
        "mandatory_capabilities_available": mandatory_available
        and capability_age is not None
        and capability_age <= 900,
        "roster_last_complete_age_seconds": roster_age,
        "roster_fresh": roster_fresh,
        "webhook_config_readback_age_seconds": webhook_proof.age_seconds,
        "webhook_config_stale": webhook_proof.stale,
        "webhook_config_status": webhook_proof.status,
        "webhook_config_rejection_reason": webhook_proof.rejection_reason,
        "webhook_config_verified": webhook_proof.verified,
    }


def provider_assignment_rejection_reason() -> str | None:
    """Return the first failed provider gate without lifecycle/readiness coupling."""
    if settings.HUBSPOT_PROVIDER_CONTRACT_MODE != "enforce":
        return None
    try:
        checks = _provider_access_checks(timezone.now())
    except ValueError, TypeError, KeyError, OSError, RedisError:
        return "provider_evidence_unavailable"
    if not checks["canonical_capacity_writer"]:
        return "canonical_capacity_writer_inactive"
    if not checks["mandatory_capabilities_available"]:
        return "provider_capabilities_unavailable"
    if not checks["roster_fresh"]:
        return "provider_roster_stale"
    if not checks["webhook_config_verified"]:
        return f"provider_webhook_proof_{checks['webhook_config_rejection_reason']}"
    return None


def provider_assignment_allowed() -> bool:
    """Fail closed before an owner PATCH when required provider evidence is invalid."""
    return provider_assignment_rejection_reason() is None


def provider_contract_checks(now: datetime | None = None) -> dict[str, Any]:
    """Expose capability, roster and occurrence lag without identifiers or payloads."""
    now = now or timezone.now()
    checks = _provider_access_checks(now)
    if checks["mode"] == "off":
        return checks
    checks["warnings"] = []
    if checks["webhook_config_verified"] and checks["webhook_config_stale"]:
        checks["warnings"].append("hubspot_webhook_config_stale")
        logger.warning(
            "hubspot_webhook_proof_stale",
            age_seconds=checks["webhook_config_readback_age_seconds"],
        )
    checks["occurrence_migration_applied"] = False
    migrated = (
        MigrationRecorder(connection)
        .migration_qs.filter(app="support", name="0033_supportlifecycleoccurrence")
        .exists()
    )
    checks["occurrence_migration_applied"] = migrated
    if migrated:
        from apps.support.models import SupportLifecycleOccurrence

        checks["occurrences_by_status"] = {
            row["evidence_status"]: row["count"]
            for row in SupportLifecycleOccurrence.objects.values("evidence_status").annotate(count=Count("id"))
        }
        pending = SupportLifecycleOccurrence.objects.filter(
            occurrence_type=SupportLifecycleOccurrence.Type.CLOSED,
            evidence_status=SupportLifecycleOccurrence.EvidenceStatus.PROVIDER_MATERIALIZATION_PENDING,
            processing_status=SupportLifecycleOccurrence.ProcessingStatus.PENDING,
        )
        oldest = pending.order_by("created_at").values_list("created_at", flat=True).first()
        checks["pending_close_count"] = pending.count()
        checks["oldest_pending_close_age_seconds"] = max(0, int((now - oldest).total_seconds())) if oldest else 0
        checks["repair_required_count"] = SupportLifecycleOccurrence.objects.filter(
            processing_status=SupportLifecycleOccurrence.ProcessingStatus.REPAIR_REQUIRED
        ).count()
    return checks


def provider_contract_reasons(checks: dict[str, Any]) -> tuple[str, ...]:
    """Return blockers only when provider contract enforcement is enabled."""
    if checks.get("mode") != "enforce":
        return ()
    reasons = []
    if not checks.get("canonical_capacity_writer"):
        reasons.append("canonical_capacity_writer_inactive")
    if not checks.get("mandatory_capabilities_available"):
        reasons.append("hubspot_capabilities_unavailable")
    if not checks.get("roster_fresh"):
        reasons.append("hubspot_roster_stale")
    if not checks.get("webhook_config_verified"):
        reasons.append(f"hubspot_webhook_config_{checks.get('webhook_config_rejection_reason') or 'invalid'}")
    if not checks.get("occurrence_migration_applied"):
        reasons.append("lifecycle_occurrence_migration_missing")
    if checks.get("repair_required_count", 0):
        reasons.append("lifecycle_occurrence_repair_required")
    if checks.get("oldest_pending_close_age_seconds", 0) >= settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_AGE_SECONDS:
        reasons.append("lifecycle_close_materialization_stale")
    return tuple(reasons)
