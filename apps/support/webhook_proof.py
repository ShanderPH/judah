"""Durable evidence of published HubSpot configuration, independent of freshness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.integrations.hubspot.webhook_config import (
    compare_app_config,
    compare_webhook_config,
    load_private_configuration,
)

WEBHOOK_CONFIG_CACHE_KEY = "hubspot_webhook_config_readback"
WEBHOOK_PROOF_STALE_SECONDS = 86400


class WebhookProof(TypedDict):
    """Versioned snapshot written only after comparing both published exports."""

    schema_version: int
    checked_at: str
    ready: bool
    config_fingerprint: str


@dataclass(frozen=True, slots=True)
class WebhookProofEvaluation:
    """Validity and freshness are separate observations of the same evidence."""

    status: str
    age_seconds: int | None = None
    stale: bool = False

    @property
    def verified(self) -> bool:
        """Return whether evidence applies to the current configuration."""
        return self.status == "valid"

    @property
    def rejection_reason(self) -> str | None:
        """Return the bounded, PII-free reason for rejecting this proof."""
        if self.verified:
            return None
        if self.status in {"missing", "fingerprint_mismatch"}:
            return self.status
        return "invalid"


def load_desired_configuration() -> tuple[dict[str, object], dict[str, object]]:
    """Read both desired manifests from the private deployment configuration."""
    _, webhooks, app = load_private_configuration(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    return webhooks, app


def configuration_fingerprint(
    webhooks: dict[str, object], app: dict[str, object], *, contract_version: str = "1"
) -> str:
    """Hash the private revision and both complete manifests with canonical ordering."""
    canonical = json.dumps(
        {"contract_version": contract_version, "app": app, "webhooks": webhooks},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def expected_configuration_fingerprint() -> str:
    """Compute the identity expected by this running version."""
    version, webhooks, app = load_private_configuration(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    return configuration_fingerprint(webhooks, app, contract_version=version)


def _store_proof(*, ready: bool, fingerprint: str) -> WebhookProof:
    """Persist a new observation without a destructive cache timeout."""
    proof: WebhookProof = {
        "schema_version": 1,
        "checked_at": timezone.now().isoformat(),
        "ready": ready,
        "config_fingerprint": fingerprint,
    }
    cache.set(WEBHOOK_CONFIG_CACHE_KEY, proof, timeout=None)
    return proof


def invalidate_webhook_proof() -> WebhookProof:
    """Replace prior evidence when a published export cannot be read."""
    try:
        fingerprint = expected_configuration_fingerprint()
    except ValueError:
        fingerprint = ""
    return _store_proof(ready=False, fingerprint=fingerprint)


def record_published_configuration(
    published_webhooks: dict[str, object], published_app: dict[str, object]
) -> WebhookProof:
    """Compare both exports and persist the outcome without an expiration timer.

    Invalid exports also replace prior evidence with a fail-closed snapshot.
    The caller must fail its release gate when the returned proof is not ready.
    """
    try:
        version, desired_webhooks, desired_app = load_private_configuration(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    except ValueError:
        _store_proof(ready=False, fingerprint="")
        raise
    fingerprint = configuration_fingerprint(desired_webhooks, desired_app, contract_version=version)
    try:
        webhook_result = compare_webhook_config(desired_webhooks, published_webhooks)
        app_result = compare_app_config(desired_app, published_app)
    except ValueError, KeyError, TypeError, AttributeError:
        _store_proof(ready=False, fingerprint=fingerprint)
        raise
    return _store_proof(ready=webhook_result["ready"] is True and app_result["ready"] is True, fingerprint=fingerprint)


def evaluate_webhook_proof(snapshot: object, *, expected_fingerprint: str, now: datetime) -> WebhookProofEvaluation:
    """Reject absent, invalid, legacy or incompatible evidence, never age alone."""
    if snapshot is None:
        return WebhookProofEvaluation("missing")
    if not isinstance(snapshot, dict):
        return WebhookProofEvaluation("invalid")
    try:
        checked_at = datetime.fromisoformat(snapshot["checked_at"])
        age = max(0, int((now - checked_at).total_seconds()))
    except KeyError, ValueError, TypeError, OverflowError:
        return WebhookProofEvaluation("invalid")
    stale = age > WEBHOOK_PROOF_STALE_SECONDS
    if snapshot.get("ready") is not True:
        return WebhookProofEvaluation("invalid", age, stale)
    if not snapshot.get("config_fingerprint"):
        return WebhookProofEvaluation("fingerprint_missing", age, stale)
    if snapshot.get("schema_version") != 1:
        return WebhookProofEvaluation("invalid", age, stale)
    if snapshot["config_fingerprint"] != expected_fingerprint:
        return WebhookProofEvaluation("fingerprint_mismatch", age, stale)
    return WebhookProofEvaluation("valid", age, stale)
