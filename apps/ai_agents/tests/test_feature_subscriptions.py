"""Tests for the best-effort InRadar feature-subscription lookup."""

from __future__ import annotations

import json

import httpx
from django.test import override_settings

from apps.ai_agents.services.feature_subscriptions import (
    fetch_active_feature_subscriptions,
    fetch_church_plan,
    normalize_church_id,
)

FEATURE_URL = "https://inradar.test/feature-subscriptions"
CHURCH_URL = "https://inradar.test/tertiarygroup"


def test_normalize_church_id_accepts_numeric_and_legacy_t_prefix() -> None:
    assert normalize_church_id("35120") == "35120"
    assert normalize_church_id("T35120") == "35120"
    assert normalize_church_id(653) == "653"
    assert normalize_church_id("local-35120") is None


@override_settings(
    INRADAR_FEATURE_SUBSCRIPTIONS_URL=FEATURE_URL,
    INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN="test-basic-token",
    INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS=1,
)
def test_fetch_active_feature_subscriptions_normalizes_provider_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Basic test-basic-token"
        assert json.loads(request.content) == {
            "tertiarygroup": 653,
            "is_active": True,
        }
        return httpx.Response(
            200,
            json=[
                {
                    "feature": {"alias": "kids"},
                    "plan": {
                        "name": "1001 - 2500 pessoas na igreja",
                        "price": "329.90",
                        "limit": 2500,
                    },
                    "is_active": True,
                },
                {
                    "feature": {"alias": "smart_store"},
                    "plan": {"name": "Loja", "price": "199.90", "limit": None},
                    "is_active": True,
                },
                {
                    "feature": {"alias": "kids"},
                    "plan": {"name": "registro duplicado", "price": "999.99", "limit": 9999},
                    "is_active": True,
                },
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_active_feature_subscriptions("T653", client=client)

    assert result.status == "success"
    assert result.church_id == "653"
    assert [module.as_dict() for module in result.modules] == [
        {
            "alias": "kids",
            "name": "1001 - 2500 pessoas na igreja",
            "price": "329.90",
            "plan_limit": "2500",
        },
        {
            "alias": "smart_store",
            "name": "Loja",
            "price": "199.90",
            "plan_limit": None,
        },
    ]


@override_settings(
    INRADAR_FEATURE_SUBSCRIPTIONS_URL=FEATURE_URL,
    INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN="test-basic-token",
    INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS=1,
)
def test_fetch_active_feature_subscriptions_reports_empty_result() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[]))) as client:
        result = fetch_active_feature_subscriptions("653", client=client)

    assert result.status == "no_modules"
    assert result.modules == ()
    assert result.message == "Nenhum módulo ativo foi retornado."


@override_settings(INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN="")
def test_fetch_active_feature_subscriptions_does_not_call_provider_without_token() -> None:
    result = fetch_active_feature_subscriptions("653")

    assert result.status == "not_configured"
    assert result.modules == ()


@override_settings(
    INRADAR_FEATURE_SUBSCRIPTIONS_URL=FEATURE_URL,
    INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN="test-basic-token",
    INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS=1,
)
def test_fetch_active_feature_subscriptions_never_raises_on_provider_error() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(400))) as client:
        result = fetch_active_feature_subscriptions("25048", client=client)

    assert result.status == "provider_error"
    assert result.church_id == "25048"
    assert result.message == "InRadar retornou HTTP 400."


def test_fetch_active_feature_subscriptions_handles_missing_and_invalid_church_id() -> None:
    missing = fetch_active_feature_subscriptions(None)
    invalid = fetch_active_feature_subscriptions("local-35120")

    assert missing.status == "missing_church_id"
    assert invalid.status == "invalid_church_id"


@override_settings(
    INRADAR_TERTIARYGROUP_URL=CHURCH_URL,
    INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN="test-basic-token",
    INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS=1,
)
def test_fetch_church_plan_returns_plan_and_status_flags() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Basic test-basic-token"
        assert json.loads(request.content) == {"id": 25048}
        return httpx.Response(
            200,
            json={
                "id": 25048,
                "plan": "pro",
                "is_active": True,
                "is_blocked": False,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_church_plan("25048", client=client)

    assert result.status == "success"
    assert result.as_handoff_payload() == {
        "church_plan_lookup_status": "success",
        "church_plan_lookup_message": "",
        "church_plan": {
            "plan": "pro",
            "is_active": True,
            "is_blocked": False,
        },
    }


@override_settings(
    INRADAR_TERTIARYGROUP_URL=CHURCH_URL,
    INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN="test-basic-token",
    INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS=1,
)
def test_fetch_church_plan_rejects_incomplete_provider_response_without_raising() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"plan": "pro"}))
    ) as client:
        result = fetch_church_plan("25048", client=client)

    assert result.status == "invalid_response"
    assert result.plan is None


@override_settings(
    INRADAR_TERTIARYGROUP_URL=CHURCH_URL,
    INRADAR_FEATURE_SUBSCRIPTIONS_BASIC_TOKEN="test-basic-token",
    INRADAR_FEATURE_SUBSCRIPTIONS_TIMEOUT_SECONDS=1,
)
def test_fetch_church_plan_never_raises_on_provider_error() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503))) as client:
        result = fetch_church_plan("25048", client=client)

    assert result.status == "provider_error"
    assert result.message == "InRadar retornou HTTP 503."
