"""Read-only operational checks for the HubSpot provider contract."""

from __future__ import annotations

import json
from contextlib import suppress
from io import StringIO
from typing import TypedDict, cast
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.integrations.hubspot.exceptions import HubSpotAPIError
from apps.integrations.hubspot.team_roster import TeamMember, TeamRoster, TeamRosterProvider

COMMAND_MODULE = "apps.support.management.commands.check_hubspot_provider_contract"


class PreflightResult(TypedDict):
    mode: str
    team_id: str
    ready: bool
    capabilities: dict[str, str]
    portal: dict[str, object]
    roster: dict[str, object]


def _transport(*, forbidden_path: str = "") -> Mock:
    transport = Mock()

    def get_json(path: str, **_kwargs: object) -> dict[str, object]:
        if forbidden_path and forbidden_path in path:
            raise HubSpotAPIError("forbidden", external_status=403)
        if path.endswith("/members"):
            return {"results": [{"userId": "1", "type": "PRIMARY"}]}
        if path == "/crm/owners/2026-09":
            return {"results": [{"userId": "1", "id": "101"}]}
        if path == "/settings/users/2026-09/1":
            return {"id": "1", "active": True}
        if path == "/account-info/v3/details":
            return {"portalId": 47354717}
        return {"results": []}

    transport.get_json.side_effect = get_json
    return transport


def _run(settings: object, transport: Mock) -> PreflightResult:
    settings.HUBSPOT_ACCESS_TOKEN = "test-secret"
    settings.HUBSPOT_N1_TEAM_ID = "54655589"
    settings.HUBSPOT_PORTAL_ID = "47354717"
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "off"
    settings.HUBSPOT_TICKETS_WRITE_VERIFIED = False
    stdout = StringIO()
    with patch(f"{COMMAND_MODULE}.HubSpotTransport", return_value=transport), suppress(CommandError):
        call_command("check_hubspot_provider_contract", stdout=stdout)
    return cast(PreflightResult, json.loads(stdout.getvalue()))


def test_preflight_checks_capabilities_and_roster_in_off_mode_without_writes(settings) -> None:
    transport = _transport()
    result = _run(settings, transport)
    assert result["mode"] == "off"
    assert result["team_id"] == "54655589"
    assert result["portal"] == {"matches_expected": True, "outcome": "available", "portal_id": 47354717}
    assert result["ready"] is True
    assert result["capabilities"]["tickets_write"] == "unverified"
    assert result["roster"] == {
        "complete": True,
        "outcome": "available",
        "pages_read": 1,
        "member_count": 1,
        "active_count": 1,
        "owner_missing_count": 0,
        "membership_type_counts": {"PRIMARY": 1},
    }
    transport.patch_json.assert_not_called()


@pytest.mark.parametrize(
    "path, capability", [("/crm/owners/", "owners_read"), ("/settings/teams/", "teams_membership")]
)
def test_preflight_fails_on_required_403(settings, path: str, capability: str) -> None:
    result = _run(settings, _transport(forbidden_path=path))
    assert result["ready"] is False
    assert result["capabilities"][capability] == "forbidden"
    assert result["roster"]["complete"] is False


def test_preflight_fails_on_incomplete_roster(settings) -> None:
    transport = _transport()
    roster = TeamRoster((TeamMember("1", "PRIMARY", "active", 101),), False, "next", 20)
    with patch(f"{COMMAND_MODULE}.TeamRosterProvider.fetch", return_value=roster):
        result = _run(settings, transport)
    assert result["ready"] is False
    assert result["roster"]["outcome"] == "incomplete"


def test_preflight_fails_when_active_member_has_no_owner(settings) -> None:
    transport = _transport()
    roster = TeamRoster((TeamMember("1", "DEFAULT", "owner_missing"),), True, None, 1)
    with patch(f"{COMMAND_MODULE}.TeamRosterProvider.fetch", return_value=roster):
        result = _run(settings, transport)
    assert result["ready"] is False
    assert result["roster"]["owner_missing_count"] == 1


def test_preflight_fails_on_wrong_portal(settings) -> None:
    transport = _transport()
    settings.HUBSPOT_ACCESS_TOKEN = "test-secret"
    settings.HUBSPOT_N1_TEAM_ID = "54655589"
    settings.HUBSPOT_PORTAL_ID = "999"
    stdout = StringIO()
    with patch(f"{COMMAND_MODULE}.HubSpotTransport", return_value=transport), pytest.raises(CommandError):
        call_command("check_hubspot_provider_contract", stdout=stdout)
    result = json.loads(stdout.getvalue())
    assert result["portal"]["matches_expected"] is False
    transport.patch_json.assert_not_called()


def test_owner_pagination_resolves_owner_after_first_hundred() -> None:
    transport = Mock()
    transport.get_json.side_effect = [
        {
            "results": [{"userId": str(index), "id": str(index + 1000)} for index in range(100)],
            "paging": {"next": {"after": "page-two"}},
        },
        {"results": [{"userId": "100", "id": "1100"}]},
    ]
    owners = TeamRosterProvider(transport)._load_owner_ids(max_pages=2)
    assert len(owners) == 101
    assert owners["100"] == 1100
    assert transport.get_json.call_args_list[1].kwargs["params"]["after"] == "page-two"


@pytest.mark.parametrize("path", ["/settings/teams/2026-09/8/members", "/crm/owners/2026-09"])
@pytest.mark.parametrize("cursor", ["", None, 123])
def test_roster_rejects_malformed_cursor(path: str, cursor: object) -> None:
    transport = Mock()

    def get_json(request_path: str, **_kwargs: object) -> dict[str, object]:
        if request_path == path:
            return {"results": [], "paging": {"next": {"after": cursor}}}
        return {"results": [{"userId": "1"}]}

    transport.get_json.side_effect = get_json
    with pytest.raises(HubSpotAPIError, match="cursor"):
        TeamRosterProvider(transport).fetch("8")


@pytest.mark.parametrize("path", ["/settings/teams/2026-09/8/members", "/crm/owners/2026-09"])
def test_roster_rejects_repeated_cursor(path: str) -> None:
    transport = Mock()

    def get_json(request_path: str, **_kwargs: object) -> dict[str, object]:
        if request_path == path:
            return {"results": [], "paging": {"next": {"after": "repeat"}}}
        return {"results": [{"userId": "1"}]}

    transport.get_json.side_effect = get_json
    with pytest.raises(HubSpotAPIError, match="cursor"):
        TeamRosterProvider(transport).fetch("8")


def test_preflight_command_exits_nonzero_on_provider_failure(settings) -> None:
    transport = _transport(forbidden_path="/crm/owners/")
    settings.HUBSPOT_ACCESS_TOKEN = "test-secret"
    settings.HUBSPOT_N1_TEAM_ID = "54655589"
    settings.HUBSPOT_PORTAL_ID = "47354717"
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "off"
    stdout = StringIO()
    with patch(f"{COMMAND_MODULE}.HubSpotTransport", return_value=transport), pytest.raises(CommandError):
        call_command("check_hubspot_provider_contract", stdout=stdout)
    assert json.loads(stdout.getvalue())["ready"] is False
    assert "test-secret" not in stdout.getvalue()
