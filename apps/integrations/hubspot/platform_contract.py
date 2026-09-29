"""Versioned HubSpot read contracts and capability checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import requests

from apps.integrations.hubspot.exceptions import HubSpotAPIError, HubSpotFailureKind

HUBSPOT_API_BASE_URL = "https://api.hubapi.com"


class HubSpotCapability(StrEnum):
    """Capabilities used by the support integration."""

    TICKETS_READ = "tickets_read"
    TICKETS_WRITE = "tickets_write"
    OWNERS_READ = "owners_read"
    TEAMS_MEMBERSHIP = "teams_membership"
    USERS_READ = "users_read"
    CONVERSATIONS_READ = "conversations_read"
    JOURNAL_READ = "journal_read"


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    """Pinned API family and a safe, read-only probe where available."""

    version: str
    probe_path: str | None
    required: bool


CAPABILITY_CONTRACTS: dict[HubSpotCapability, CapabilityContract] = {
    HubSpotCapability.TICKETS_READ: CapabilityContract("2026-09", "/crm/objects/2026-09/tickets", True),
    HubSpotCapability.TICKETS_WRITE: CapabilityContract("2026-09", None, True),
    HubSpotCapability.OWNERS_READ: CapabilityContract("2026-09", "/crm/owners/2026-09", True),
    HubSpotCapability.TEAMS_MEMBERSHIP: CapabilityContract("2026-09", None, True),
    HubSpotCapability.USERS_READ: CapabilityContract("2026-09", "/settings/users/2026-09", True),
    HubSpotCapability.CONVERSATIONS_READ: CapabilityContract("2026-09", "/conversations/2026-09/inboxes", False),
    HubSpotCapability.JOURNAL_READ: CapabilityContract("unverified", None, False),
}


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    """Outcome of one read-only capability probe."""

    capability: HubSpotCapability
    version: str
    required: bool
    outcome: str
    http_status: int | None = None


class HubSpotTransport:
    """Translate HTTP responses into typed provider outcomes without domain rules."""

    def __init__(self, access_token: str, *, timeout: tuple[float, float] = (5.0, 15.0)) -> None:
        self._access_token = access_token
        self._timeout = timeout

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the fixed HubSpot host with shared timeout and error classification."""
        if not path.startswith("/") or "//" in path or ".." in path:
            raise ValueError("Invalid HubSpot API path")
        try:
            response = requests.request(
                method,
                f"{HUBSPOT_API_BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self._access_token}"},
                params=params,
                json=payload,
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise HubSpotAPIError(
                "HubSpot request timed out.", retryable=True, error_code=HubSpotFailureKind.TIMEOUT
            ) from exc
        except requests.RequestException as exc:
            raise HubSpotAPIError("HubSpot request failed.", retryable=True) from exc
        status = response.status_code
        if not 200 <= status < 300:
            kind = (
                HubSpotFailureKind.NOT_FOUND
                if status == 404
                else HubSpotFailureKind.UNAUTHORIZED
                if status == 401
                else HubSpotFailureKind.FORBIDDEN
                if status == 403
                else HubSpotFailureKind.RATE_LIMITED
                if status == 429
                else HubSpotFailureKind.SERVER_ERROR
                if status >= 500
                else HubSpotFailureKind.UNKNOWN
            )
            raise HubSpotAPIError(
                "HubSpot rejected a request.",
                external_status=status,
                retryable=status == 429 or status >= 500,
                error_code=kind,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise HubSpotAPIError(
                "HubSpot returned malformed JSON.", retryable=True, error_code=HubSpotFailureKind.MALFORMED_RESPONSE
            ) from exc
        if not isinstance(body, dict):
            raise HubSpotAPIError(
                "HubSpot returned an invalid JSON object.",
                retryable=True,
                error_code=HubSpotFailureKind.MALFORMED_RESPONSE,
            )
        return body

    def get_json(self, path: str, *, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        """Read one HubSpot JSON object."""
        return self._request_json("GET", path, params=params)

    def patch_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Patch one HubSpot JSON object with the same error contract."""
        return self._request_json("PATCH", path, payload=payload)


def check_hubspot_capabilities(
    transport: HubSpotTransport, *, team_id: str | None = None
) -> tuple[CapabilityResult, ...]:
    """Probe readable capabilities without performing any remote mutation."""
    results = []
    for capability, contract in CAPABILITY_CONTRACTS.items():
        path = contract.probe_path
        if capability == HubSpotCapability.TEAMS_MEMBERSHIP and team_id:
            if not team_id.isdigit():
                raise ValueError("HubSpot team ID must be numeric")
            path = f"/settings/teams/2026-09/{team_id}/members"
        if path is None:
            results.append(CapabilityResult(capability, contract.version, contract.required, "unverified"))
            continue
        try:
            transport.get_json(path, params={"limit": 1})
        except HubSpotAPIError as exc:
            outcome = (
                "unauthorized"
                if exc.external_status == 401
                else "forbidden"
                if exc.external_status == 403
                else "not_found"
                if exc.external_status == 404
                else "rate_limited"
                if exc.external_status == 429
                else "server_error"
                if exc.external_status is not None and exc.external_status >= 500
                else "provider_unavailable"
            )
            results.append(
                CapabilityResult(capability, contract.version, contract.required, outcome, exc.external_status)
            )
        else:
            results.append(CapabilityResult(capability, contract.version, contract.required, "available", 200))
    return tuple(results)
