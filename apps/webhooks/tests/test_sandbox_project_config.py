"""Contract checks for the HubSpot sandbox webhook project."""

import json
from pathlib import Path


def test_sandbox_manifest_has_no_legacy_bot_subscription() -> None:
    root = Path(__file__).resolve().parents[3]
    config = json.loads(
        (root / "inchurch-sandbox" / "src" / "app" / "webhooks" / "sandbox-webhooks-hsmeta.json").read_text(
            encoding="utf-8"
        )
    )["config"]

    assert config["subscriptions"]["hubEvents"] == []
    assert config["subscriptions"]["legacyCrmObjects"] == [
        {
            "subscriptionType": "ticket.propertyChange",
            "propertyName": "hubspot_owner_id",
            "active": True,
        }
    ]
