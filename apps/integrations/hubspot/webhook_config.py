"""Compare desired HubSpot project webhooks with a published readback export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Manifest and readback are untyped JSON documents at this boundary.


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
    """Compare a HubSpot published export to the versioned desired manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("published", type=Path, help="JSON readback exported from the published HubSpot app")
    parser.add_argument("--published-app", type=Path, required=True, help="Published app metadata JSON readback")
    parser.add_argument(
        "--desired",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json",
    )
    parser.add_argument(
        "--desired-app",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "hubspot-app/src/app/app-hsmeta.json",
    )
    args = parser.parse_args()
    result = compare_webhook_config(
        json.loads(args.desired.read_text(encoding="utf-8")),
        json.loads(args.published.read_text(encoding="utf-8")),
    )
    result["app"] = compare_app_config(
        json.loads(args.desired_app.read_text(encoding="utf-8")),
        json.loads(args.published_app.read_text(encoding="utf-8")),
    )
    result["ready"] = result["ready"] and result["app"]["ready"]
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
