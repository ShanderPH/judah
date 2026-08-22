"""Contract checks for the production HubSpot webhook project."""

import json
from pathlib import Path


def test_production_manifest_contains_only_operational_subscriptions() -> None:
    root = Path(__file__).resolve().parents[3]
    config = json.loads(
        (root / "hubspot-app" / "src" / "app" / "webhooks" / "judah-webhooks-hsmeta.json").read_text(encoding="utf-8")
    )["config"]
    properties = {item["propertyName"] for item in config["subscriptions"]["legacyCrmObjects"]}

    assert config["subscriptions"]["hubEvents"] == []
    assert properties == {
        "hs_v2_date_entered_939275049",
        "hs_v2_date_entered_939275052",
        "hubspot_owner_id",
    }
