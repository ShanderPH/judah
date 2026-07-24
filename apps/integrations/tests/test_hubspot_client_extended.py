"""Extended unit coverage for the HubSpot client without network calls."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from django.test import override_settings

from apps.integrations.hubspot import client as hubspot_module
from apps.integrations.hubspot.client import HubSpotClient
from apps.integrations.hubspot.exceptions import HubSpotAPIError
from common.exceptions import ExternalServiceError


def _client() -> HubSpotClient:
    client = HubSpotClient.__new__(HubSpotClient)
    client._access_token = "token"
    client._client = Mock()
    return client


def test_get_ticket_and_details_success() -> None:
    client = _client()
    basic = client._client.crm.tickets.basic_api
    basic.get_by_id.side_effect = [
        SimpleNamespace(
            id="1",
            properties={
                "subject": "Falha",
                "hs_ticket_priority": "HIGH",
                "hs_pipeline_stage": "open",
                "hubspot_owner_id": "10",
            },
        ),
        SimpleNamespace(
            id="1",
            properties={
                "subject": "Falha",
                "hs_ticket_priority": "HIGH",
                "hs_pipeline": "support",
                "hs_pipeline_stage": "open",
                "hubspot_owner_id": None,
                "firstname": "Ana",
                "email": "ana@example.com",
            },
        ),
    ]
    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs),
    ):
        assert client.get_ticket("1") == {
            "id": "1",
            "subject": "Falha",
            "priority": "HIGH",
            "stage": "open",
            "owner_id": "10",
        }
        details = client.get_ticket_details("1", properties=["subject"])

    assert details["owner_id"] == ""
    basic.get_by_id.assert_called_with("1", properties=["subject"])


@pytest.mark.parametrize("method", ["get_ticket", "get_ticket_details"])
def test_ticket_reads_wrap_errors(method: str) -> None:
    client = _client()
    with (
        patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")),
        pytest.raises(ExternalServiceError),
    ):
        getattr(client, method)("1")


def test_contact_lookup_and_search_paths() -> None:
    client = _client()
    client._client.crm.contacts.basic_api.get_by_id.return_value = SimpleNamespace(
        id="c1",
        properties={"email": "a@example.com", "firstname": "Ana", "lastname": "Silva"},
    )
    found = SimpleNamespace(
        id="c1",
        properties={"firstname": "Ana", "lastname": "Silva", "company": "Igreja", "lifecyclestage": "customer"},
    )
    client._client.crm.contacts.search_api.do_search.side_effect = [
        SimpleNamespace(results=[found]),
        SimpleNamespace(results=[]),
    ]
    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs),
    ):
        assert client.get_contact_by_id("c1")["email"] == "a@example.com"
        assert client.search_contact_by_email("a@example.com")["company"] == "Igreja"
        assert client.search_contact_by_email("none@example.com") == {}


def test_contact_lookup_errors_are_safe_or_wrapped() -> None:
    client = _client()
    with patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")):
        assert client.get_contact_by_id("c1") == {}
        with pytest.raises(ExternalServiceError):
            client.search_contact_by_email("a@example.com")


@override_settings(
    HUBSPOT_DEFAULT_TICKET_PIPELINE_ID="pipeline",
    HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID="new",
)
def test_create_ticket_success_and_error() -> None:
    client = _client()
    client._client.crm.tickets.basic_api.create.return_value = SimpleNamespace(id="t1")
    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs),
    ):
        assert client.create_ticket("Assunto", priority="high") == {"id": "t1", "subject": "Assunto"}

    with (
        patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")),
        pytest.raises(ExternalServiceError),
    ):
        client.create_ticket("Assunto")


def test_assign_ticket_owner_success_and_generic_failure() -> None:
    client = _client()
    client._client.crm.tickets.basic_api.update.return_value = SimpleNamespace(id="t1")
    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs),
    ):
        assert client.assign_ticket_owner("t1", 10) == {"id": "t1", "owner_id": 10}

    with (
        patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")),
        pytest.raises(HubSpotAPIError) as captured,
    ):
        client.assign_ticket_owner("t1", 10)
    assert captured.value.retryable is True


def test_owner_and_team_queries() -> None:
    client = _client()
    team = SimpleNamespace(id="8", name="N1")
    owner = SimpleNamespace(
        id=10,
        email="ana@example.com",
        first_name="Ana",
        last_name="Silva",
        user_id=99,
        teams=[team],
    )
    other = SimpleNamespace(id=11, email="b@example.com", first_name="B", last_name="C", teams=[])
    client._client.crm.owners.owners_api.get_by_id.return_value = owner
    client._client.crm.owners.owners_api.get_page.return_value = SimpleNamespace(results=[owner, other])
    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs),
    ):
        details = client.get_owner_details(10)
        members = client.get_team_members("8")

    assert details["teams"] == [{"id": "8", "name": "N1"}]
    assert members == [{"id": 10, "email": "ana@example.com", "first_name": "Ana", "last_name": "Silva"}]


def test_owner_queries_handle_errors() -> None:
    client = _client()
    with patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")):
        assert client.get_owner_details(10) == {}
        with pytest.raises(ExternalServiceError):
            client.get_team_members("8")


def test_search_novo_stage_paginates_and_maps_results() -> None:
    client = _client()
    first = Mock()
    first.json.return_value = {
        "results": [
            {
                "id": "t1",
                "properties": {
                    "subject": "A",
                    "hs_ticket_priority": "HIGH",
                    "hs_pipeline": hubspot_module.SUPPORT_PIPELINE_ID,
                    "hs_pipeline_stage": hubspot_module.STAGE_NOVO_ID,
                    "hubspot_owner_id": None,
                },
            }
        ],
        "paging": {"next": {"after": "cursor"}},
    }
    second = Mock()
    second.json.return_value = {"results": [{"id": "t2", "properties": None}]}
    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        side_effect=[first, second],
    ):
        results = client.search_tickets_in_novo_stage()

    assert [item["id"] for item in results] == ["t1", "t2"]
    assert results[0]["owner_id"] == ""
    first.raise_for_status.assert_called_once()
    second.raise_for_status.assert_called_once()


def test_search_novo_stage_wraps_errors() -> None:
    with (
        patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")),
        pytest.raises(ExternalServiceError),
    ):
        _client().search_tickets_in_novo_stage()


def test_user_lookup_success_and_failure() -> None:
    response = Mock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {
        "id": "u1",
        "properties": {"hs_email": "ana@example.com", "hs_availability_status": "available"},
    }
    with patch("apps.integrations.hubspot.client._circuit_breaker.call", return_value=response):
        assert _client().get_user_by_id("u1")["hs_availability_status"] == "available"

    with (
        patch(
            "apps.integrations.hubspot.client._circuit_breaker.call",
            side_effect=requests.ConnectionError("offline"),
        ),
        pytest.raises(HubSpotAPIError),
    ):
        _client().get_user_by_id("u1")


def test_owner_availability_cache_and_pagination() -> None:
    cache = Mock()
    cached = [{"user_id": "cached"}]
    cache.get.return_value = cached
    with patch("django.core.cache.cache", cache):
        assert _client().get_all_owners_availability() == cached

    cache.get.return_value = None
    first = Mock()
    first.json.return_value = {
        "results": [{"id": "u1", "properties": {"hs_email": "a@example.com", "hs_availability_status": "available"}}],
        "paging": {"next": {"after": "cursor"}},
    }
    second = Mock()
    second.json.return_value = {
        "results": [{"id": "u2", "properties": {"hs_email": "b@example.com", "hs_availability_status": "away"}}]
    }
    with (
        patch("django.core.cache.cache", cache),
        patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=[first, second]),
    ):
        result = _client().get_all_owners_availability()

    assert [item["status_enum"] for item in result] == ["online", "away"]
    cache.set.assert_called_once_with("hubspot_users_availability_2026_03", result, timeout=15)


def test_owner_availability_wraps_errors() -> None:
    cache = Mock()
    cache.get.return_value = None
    with (
        patch("django.core.cache.cache", cache),
        patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")),
        pytest.raises(ExternalServiceError),
    ):
        _client().get_all_owners_availability()


def test_count_active_tickets_success_and_error() -> None:
    response = Mock()
    response.json.return_value = {"total": 7}
    with patch("apps.integrations.hubspot.client._circuit_breaker.call", return_value=response):
        assert _client().count_active_tickets_by_owner(10) == 7
    response.raise_for_status.assert_called_once()

    with patch("apps.integrations.hubspot.client._circuit_breaker.call", side_effect=RuntimeError("offline")):
        assert _client().count_active_tickets_by_owner(10) == -1


@override_settings(HUBSPOT_ACCESS_TOKEN="")
def test_hubspot_singleton_requires_token() -> None:
    hubspot_module._hubspot_client = None
    with pytest.raises(ValueError):
        hubspot_module.get_hubspot_client()


@override_settings(HUBSPOT_ACCESS_TOKEN="token")
def test_hubspot_singleton_reuses_client() -> None:
    hubspot_module._hubspot_client = None
    sentinel = Mock(spec=HubSpotClient)
    with patch("apps.integrations.hubspot.client.HubSpotClient", return_value=sentinel) as factory:
        assert hubspot_module.get_hubspot_client() is sentinel
        assert hubspot_module.get_hubspot_client() is sentinel
    factory.assert_called_once_with(access_token="token")
