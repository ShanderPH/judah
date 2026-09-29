"""Probe HubSpot provider access without changing CRM or JUDAH state."""

from __future__ import annotations

import json
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.integrations.hubspot.exceptions import HubSpotAPIError
from apps.integrations.hubspot.platform_contract import (
    HubSpotCapability,
    HubSpotTransport,
    check_hubspot_capabilities,
)
from apps.integrations.hubspot.team_roster import TeamRosterProvider

REQUIRED_READ_CAPABILITIES = (
    HubSpotCapability.TICKETS_READ,
    HubSpotCapability.OWNERS_READ,
    HubSpotCapability.TEAMS_MEMBERSHIP,
    HubSpotCapability.USERS_READ,
)


class Command(BaseCommand):
    """Report live read capabilities and complete N1 roster independently of mode."""

    help = "Read-only HubSpot provider contract preflight, including the N1 team roster"

    def handle(self, *args: object, **options: object) -> None:
        """Print a PII-free JSON result and fail when required reads are unavailable."""
        token = settings.HUBSPOT_ACCESS_TOKEN
        team_id = settings.HUBSPOT_N1_TEAM_ID
        if not token or not team_id or not str(team_id).isdigit():
            self.stdout.write(json.dumps({"ready": False, "error": "hubspot_not_configured"}))
            raise CommandError("HubSpot provider contract preflight failed")

        transport = HubSpotTransport(token)
        results = check_hubspot_capabilities(transport, team_id=team_id)
        capabilities = {result.capability.value: result.outcome for result in results}
        if settings.HUBSPOT_TICKETS_WRITE_VERIFIED:
            capabilities[HubSpotCapability.TICKETS_WRITE.value] = "verified_in_sandbox"

        portal_result: dict[str, object] = {"matches_expected": False, "outcome": "unverified"}
        try:
            account = transport.get_json("/account-info/v3/details")
        except HubSpotAPIError as exc:
            portal_result = {"matches_expected": False, "outcome": "provider_error", "http_status": exc.external_status}
        else:
            portal_id = account.get("portalId")
            matches_expected = bool(settings.HUBSPOT_PORTAL_ID) and str(portal_id) == str(settings.HUBSPOT_PORTAL_ID)
            portal_result = {
                "matches_expected": matches_expected,
                "outcome": "available" if matches_expected else "mismatch",
                "portal_id": portal_id,
            }

        required_available = all(
            capabilities[capability.value] == "available" for capability in REQUIRED_READ_CAPABILITIES
        )
        roster_result: dict[str, object] = {"complete": False, "outcome": "unverified"}
        if required_available:
            try:
                roster = TeamRosterProvider(transport).fetch(team_id)
            except HubSpotAPIError as exc:
                roster_result = {
                    "complete": False,
                    "outcome": "provider_error",
                    "http_status": exc.external_status,
                }
            else:
                unresolved = sum(member.state == "owner_missing" for member in roster.members)
                roster_result = {
                    "complete": roster.complete,
                    "outcome": "available" if roster.complete and roster.members and not unresolved else "incomplete",
                    "pages_read": roster.pages_read,
                    "member_count": len(roster.members),
                    "active_count": sum(member.state == "active" for member in roster.members),
                    "owner_missing_count": unresolved,
                    "membership_type_counts": dict(
                        sorted(Counter(member.membership_type for member in roster.members).items())
                    ),
                }

        ready = required_available and roster_result["outcome"] == "available" and portal_result["matches_expected"]
        self.stdout.write(
            json.dumps(
                {
                    "mode": settings.HUBSPOT_PROVIDER_CONTRACT_MODE,
                    "portal": portal_result,
                    "team_id": str(team_id),
                    "capabilities": capabilities,
                    "roster": roster_result,
                    "ready": ready,
                },
                sort_keys=True,
            )
        )
        if not ready:
            raise CommandError("HubSpot provider contract preflight failed")
