"""Contract checks for production HubSpot webhook projects."""

from __future__ import annotations

import json
from pathlib import Path


def _webhook_config(project_path: str, webhook_file: str) -> dict:
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / project_path / "src" / "app" / "webhooks" / webhook_file).read_text(encoding="utf-8"))[
        "config"
    ]


def _new_message_subscription(config: dict) -> dict:
    return next(
        item for item in config["subscriptions"]["hubEvents"] if item["subscriptionType"] == "conversation.newMessage"
    )


def test_judah_is_the_active_per_message_event_source() -> None:
    judah = _webhook_config("hubspot-app", "judah-webhooks-hsmeta.json")

    assert judah["settings"]["targetUrl"] == ("https://judah-production.up.railway.app/api/v1/webhooks/hubspot/")
    assert _new_message_subscription(judah)["active"] is True


def test_legacy_boolean_message_trigger_is_disabled_when_present() -> None:
    root = Path(__file__).resolve().parents[3]
    config = json.loads(
        (root / "hubspot-app" / "src" / "app" / "webhooks" / "judah-webhooks-hsmeta.json").read_text(encoding="utf-8")
    )["config"]
    boolean_trigger = next(
        item
        for item in config["subscriptions"]["legacyCrmObjects"]
        if item.get("propertyName") == "hs_last_message_from_visitor"
    )

    assert boolean_trigger["active"] is False
