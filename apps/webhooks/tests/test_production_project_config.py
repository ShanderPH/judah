"""Contract checks using synthetic HubSpot webhook deployment configuration."""

import json

import pytest

from apps.integrations.hubspot.webhook_config import load_private_configuration, main


def test_synthetic_contract_contains_only_operational_subscriptions(settings) -> None:
    _, webhooks, _ = load_private_configuration(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    config = webhooks["config"]
    properties = {item["propertyName"] for item in config["subscriptions"]["legacyCrmObjects"]}

    assert config["subscriptions"]["hubEvents"] == []
    assert properties == {
        "hs_v2_date_entered_101",
        "hs_v2_date_entered_102",
        "hubspot_owner_id",
    }


@pytest.mark.parametrize(
    "section, field, value",
    [
        ("app", "uid", ""),
        ("webhooks", "uid", None),
        ("app", "config", {}),
        ("webhooks", "config", []),
        ("app", "config", {"auth": {"requiredScopes": "tickets"}}),
        ("app", "config", {"auth": {"requiredScopes": []}}),
    ],
)
def test_incomplete_private_contract_is_rejected(settings, section, field, value) -> None:
    document = json.loads(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    document[section][field] = value
    with pytest.raises(ValueError, match=r"^Invalid private HubSpot provider configuration$"):
        load_private_configuration(json.dumps(document))


@pytest.mark.parametrize(
    "field, value",
    [("targetUrl", ""), ("targetUrl", "https://"), ("maxConcurrentRequests", True), ("maxConcurrentRequests", 0)],
)
def test_invalid_webhook_settings_are_rejected(settings, field, value) -> None:
    document = json.loads(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    document["webhooks"]["config"]["settings"][field] = value
    with pytest.raises(ValueError):
        load_private_configuration(json.dumps(document))


@pytest.mark.parametrize("entries", [[], [None], [{"active": "true"}], [{"active": True}], [{"active": False}]])
def test_invalid_private_subscriptions_are_rejected(settings, entries) -> None:
    document = json.loads(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    document["webhooks"]["config"]["subscriptions"]["legacyCrmObjects"] = entries
    with pytest.raises(ValueError):
        load_private_configuration(json.dumps(document))


def test_cli_uses_private_environment_contract(settings, monkeypatch, tmp_path, capsys) -> None:
    _, webhooks, app = load_private_configuration(settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    webhook_path, app_path = tmp_path / "webhooks.json", tmp_path / "app.json"
    webhook_path.write_text(json.dumps(webhooks))
    app_path.write_text(json.dumps(app))
    monkeypatch.setenv("HUBSPOT_PROVIDER_CONFIG_JSON", settings.HUBSPOT_PROVIDER_CONFIG_JSON)
    monkeypatch.setattr("sys.argv", ["webhook_config", str(webhook_path), "--published-app", str(app_path)])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    app["uid"] = "wrong"
    app["config"]["auth"]["requiredScopes"] = ["private-scope"]
    app_path.write_text(json.dumps(app))
    assert main() == 1
    output = capsys.readouterr().out
    assert json.loads(output)["ready"] is False
    assert "private-scope" not in output
