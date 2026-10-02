"""Validate private desired HubSpot configuration against published exports."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Manifest and readback are untyped JSON documents at this boundary.


def load_private_configuration(raw: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Parse the private contract without exposing its contents in errors.

    Returns:
        The contract revision, desired webhooks and desired app metadata.

    Raises:
        ValueError: If any required configuration section is absent or malformed.
    """
    try:
        document = json.loads(raw)
        version, webhooks, app = document["contract_version"], document["webhooks"], document["app"]
        if not isinstance(version, str) or not version.strip():
            raise ValueError
        for manifest in (webhooks, app):
            if (
                not isinstance(manifest, dict)
                or not isinstance(manifest.get("uid"), str)
                or not manifest["uid"].strip()
            ):
                raise ValueError
            if not isinstance(manifest.get("config"), dict):
                raise ValueError
        webhook_settings = webhooks["config"]["settings"]
        target = webhook_settings["targetUrl"]
        concurrency = webhook_settings["maxConcurrentRequests"]
        if not isinstance(target, str) or urlsplit(target).scheme != "https" or not urlsplit(target).hostname:
            raise ValueError
        if type(concurrency) is not int or concurrency <= 0 or not _subscriptions(webhooks["config"]):
            raise ValueError
        subscriptions = webhooks["config"]["subscriptions"]["legacyCrmObjects"]
        if any(not isinstance(entry, dict) or type(entry.get("active")) is not bool for entry in subscriptions):
            raise ValueError
        scopes = app["config"]["auth"]["requiredScopes"]
        if (
            not isinstance(scopes, list)
            or not scopes
            or any(not isinstance(scope, str) or not scope.strip() for scope in scopes)
        ):
            raise ValueError
    except ValueError, KeyError, TypeError, AttributeError:
        raise ValueError("Invalid private HubSpot provider configuration") from None
    return version, webhooks, app


def _config(document: dict[str, Any]) -> dict[str, Any]:
    """Extract the configuration section from either supported export shape."""
    config = document.get("config", document)
    if not isinstance(config, dict):
        raise ValueError("Invalid HubSpot webhook configuration")
    return config


def _subscriptions(config: dict[str, Any]) -> set[tuple[str, str]]:
    """Identify active subscriptions by event and required property."""
    subscriptions = config.get("subscriptions")
    if not isinstance(subscriptions, dict):
        raise ValueError("Missing HubSpot webhook subscriptions")
    entries = subscriptions.get("legacyCrmObjects")
    if not isinstance(entries, list):
        raise ValueError("Missing legacy CRM webhook subscriptions")
    active = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("active") is not True:
            continue
        event = entry.get("subscriptionType")
        if not isinstance(event, str) or not event:
            raise ValueError("Active webhook subscription has no subscriptionType")
        property_name = ""
        if event.endswith(".propertyChange"):
            property_name = entry.get("propertyName")
            if not isinstance(property_name, str) or not property_name:
                raise ValueError("Property-change webhook subscription has no propertyName")
        active.add((event, property_name))
    return active


def compare_webhook_config(desired: dict[str, Any], published: dict[str, Any]) -> dict[str, Any]:
    """Report only required target, concurrency and active subscription drift."""
    expected, observed = _config(desired), _config(published)
    expected_settings, observed_settings = expected.get("settings") or {}, observed.get("settings") or {}
    expected_subscriptions = _subscriptions(expected)
    observed_subscriptions = _subscriptions(observed)
    missing = sorted(expected_subscriptions - observed_subscriptions)
    return {
        "webhook_uid_matches": desired.get("uid") == published.get("uid"),
        "target_url_matches": expected_settings.get("targetUrl") == observed_settings.get("targetUrl"),
        "concurrency_matches": expected_settings.get("maxConcurrentRequests")
        == observed_settings.get("maxConcurrentRequests"),
        "missing_active_subscriptions": [
            f"{event}:{property_name}" if property_name else event for event, property_name in missing
        ],
        "ready": (
            desired.get("uid") == published.get("uid")
            and expected_settings.get("targetUrl") == observed_settings.get("targetUrl")
            and expected_settings.get("maxConcurrentRequests") == observed_settings.get("maxConcurrentRequests")
            and not missing
        ),
    }


def compare_app_config(desired: dict[str, Any], published: dict[str, Any]) -> dict[str, Any]:
    """Detect project identity and effective required-scope drift."""
    desired_auth = _config(desired).get("auth") or {}
    published_auth = _config(published).get("auth") or {}
    desired_scopes = set(desired_auth.get("requiredScopes") or [])
    published_scopes = set(published_auth.get("requiredScopes") or [])
    identity_matches = desired.get("uid") == published.get("uid")
    return {
        "app_uid_matches": identity_matches,
        "missing_required_scopes": sorted(desired_scopes - published_scopes),
        "unexpected_required_scopes": sorted(published_scopes - desired_scopes),
        "ready": identity_matches and desired_scopes == published_scopes,
    }


def main() -> int:
    """Compare published exports to the private desired contract from the environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("published", type=Path, help="JSON readback exported from the published HubSpot app")
    parser.add_argument("--published-app", type=Path, required=True, help="Published app metadata JSON readback")
    args = parser.parse_args()
    _, desired_webhooks, desired_app = load_private_configuration(os.environ.get("HUBSPOT_PROVIDER_CONFIG_JSON", ""))
    result = compare_webhook_config(
        desired_webhooks,
        json.loads(args.published.read_text(encoding="utf-8")),
    )
    result["app"] = compare_app_config(
        desired_app,
        json.loads(args.published_app.read_text(encoding="utf-8")),
    )
    result["ready"] = result["ready"] and result["app"]["ready"]
    # Drift observations must not expose private scopes or subscription properties.
    result["missing_active_subscription_count"] = len(result.pop("missing_active_subscriptions"))
    for field in ("missing_required_scopes", "unexpected_required_scopes"):
        result["app"][f"{field}_count"] = len(result["app"].pop(field))
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
