"""Contract checks for the HubSpot sandbox webhook project."""

from __future__ import annotations

import json
from pathlib import Path


def test_sandbox_uses_per_message_event_without_boolean_fallback() -> None:
    project_file = (
        Path(__file__).resolve().parents[3]
        / "inchurch-sandbox"
        / "src"
        / "app"
        / "webhooks"
        / "sandbox-webhooks-hsmeta.json"
    )
    config = json.loads(project_file.read_text(encoding="utf-8"))["config"]
    hub_events = config["subscriptions"]["hubEvents"]
    legacy_events = config["subscriptions"]["legacyCrmObjects"]

    conversation_subscription = next(
        item for item in hub_events if item["subscriptionType"] == "conversation.newMessage"
    )
    boolean_fallback = next(
        item for item in legacy_events if item.get("propertyName") == "hs_last_message_from_visitor"
    )

    assert config["settings"]["targetUrl"].endswith("/api/v1/webhooks/hubspot/sandbox/")
    assert conversation_subscription["active"] is True
    assert boolean_fallback["active"] is False
