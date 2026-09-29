"""Complete team membership read with user and CRM owner resolution."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from apps.integrations.hubspot.exceptions import HubSpotAPIError, HubSpotFailureKind
from apps.integrations.hubspot.platform_contract import HubSpotTransport


@dataclass(frozen=True, slots=True)
class TeamMember:
    """One HubSpot team member with explicit user and owner state."""

    user_id: str
    membership_type: str
    state: str
    owner_id: int | None = None
    email: str = ""
    first_name: str = ""
    last_name: str = ""


@dataclass(frozen=True, slots=True)
class TeamRoster:
    """Bounded roster; a cursor means the provider result is incomplete."""

    members: tuple[TeamMember, ...]
    complete: bool
    next_cursor: str | None
    pages_read: int


class TeamRosterProvider:
    """Read Teams 2026-09 membership, Users identity and CRM owner mapping."""

    def __init__(self, transport: HubSpotTransport) -> None:
        self.transport = transport

    def fetch(self, team_id: str, *, max_pages: int = 20, page_size: int = 100) -> TeamRoster:
        """Read a bounded roster and expose partial pagination explicitly."""
        if not team_id.isdigit():
            raise ValueError("HubSpot team ID must be numeric")
        if max_pages < 1 or not 1 <= page_size <= 100:
            raise ValueError("Invalid team roster page budget")
        path = f"/settings/teams/2026-09/{team_id}/members"
        next_cursor: str | None = None
        seen_cursors: set[str] = set()
        memberships: dict[str, str] = {}
        pages_read = 0
        while pages_read < max_pages:
            params: dict[str, str | int] = {"limit": page_size}
            if next_cursor:
                params["after"] = next_cursor
            body = self.transport.get_json(path, params=params)
            pages_read += 1
            raw_results = body.get("results")
            if not isinstance(raw_results, list):
                raise HubSpotAPIError(
                    "HubSpot returned an invalid team membership page.",
                    retryable=True,
                    error_code=HubSpotFailureKind.MALFORMED_RESPONSE,
                )
            for item in raw_results:
                if not isinstance(item, dict) or not item.get("userId"):
                    raise HubSpotAPIError(
                        "HubSpot returned an invalid team member.",
                        retryable=True,
                        error_code=HubSpotFailureKind.MALFORMED_RESPONSE,
                    )
                user_id = str(item["userId"])
                memberships[user_id] = str(item.get("type") or "")
            paging = body.get("paging", {})
            if not isinstance(paging, dict):
                raise HubSpotAPIError("Invalid HubSpot paging data.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            next_page = paging.get("next", {})
            if not isinstance(next_page, dict):
                raise HubSpotAPIError("Invalid HubSpot paging data.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            new_cursor = next_page.get("after")
            if "next" in paging and (not isinstance(new_cursor, str) or not new_cursor.strip()):
                raise HubSpotAPIError("Invalid team roster cursor.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            if new_cursor is None:
                next_cursor = None
                break
            if new_cursor in seen_cursors:
                raise HubSpotAPIError(
                    "HubSpot repeated a roster cursor.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE
                )
            seen_cursors.add(new_cursor)
            next_cursor = new_cursor
        owner_ids = self._load_owner_ids(max_pages=max_pages) if memberships else {}
        members = tuple(
            self._resolve_member(user_id, member_type, owner_ids) for user_id, member_type in memberships.items()
        )
        return TeamRoster(members, next_cursor is None, next_cursor, pages_read)

    def _load_owner_ids(self, *, max_pages: int) -> dict[str, int]:
        """Resolve CRM owner IDs from complete Owners 2026-09 pages."""
        owner_ids: dict[str, int] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(max_pages):
            params: dict[str, str | int] = {"limit": 100}
            if cursor:
                params["after"] = cursor
            body = self.transport.get_json("/crm/owners/2026-09", params=params)
            results = body.get("results")
            if not isinstance(results, list):
                raise HubSpotAPIError("Invalid owner page.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            for owner in results:
                if not isinstance(owner, dict):
                    raise HubSpotAPIError("Invalid owner entry.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
                user_id, owner_id = owner.get("userId"), owner.get("id")
                if user_id is None or owner.get("archived") is True:
                    continue
                if owner_id is None or not str(owner_id).isdigit():
                    raise HubSpotAPIError("Invalid CRM owner ID.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
                owner_ids[str(user_id)] = int(owner_id)
            paging = body.get("paging", {})
            if not isinstance(paging, dict):
                raise HubSpotAPIError("Invalid owner paging.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            next_page = paging.get("next", {})
            if not isinstance(next_page, dict):
                raise HubSpotAPIError("Invalid owner paging.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            next_cursor = next_page.get("after")
            if "next" in paging and (not isinstance(next_cursor, str) or not next_cursor.strip()):
                raise HubSpotAPIError("Invalid owner cursor.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            if next_cursor is None:
                return owner_ids
            cursor = next_cursor
            if cursor in seen_cursors:
                raise HubSpotAPIError("Repeated owner cursor.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
            seen_cursors.add(cursor)
        raise HubSpotAPIError("Owner page budget exhausted.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)

    def _resolve_member(self, user_id: str, membership_type: str, owner_ids: dict[str, int]) -> TeamMember:
        """Resolve one membership without converting missing identity into success."""
        encoded_id = quote(user_id, safe="")
        try:
            user = self.transport.get_json(f"/settings/users/2026-09/{encoded_id}")
        except HubSpotAPIError as exc:
            if exc.external_status == 404:
                return TeamMember(user_id, membership_type, "removed")
            raise
        if not user.get("id") or str(user["id"]) != user_id:
            raise HubSpotAPIError("HubSpot user identity mismatch.", error_code=HubSpotFailureKind.MALFORMED_RESPONSE)
        state = "inactive" if user.get("active") is False or user.get("isActive") is False else "active"
        owner_id = owner_ids.get(user_id) if state == "active" else None
        if state == "active" and owner_id is None:
            state = "owner_missing"
        return TeamMember(
            user_id=user_id,
            membership_type=membership_type,
            state=state,
            owner_id=owner_id,
            email=str(user.get("email") or ""),
            first_name=str(user.get("firstName") or ""),
            last_name=str(user.get("lastName") or ""),
        )
