"""Pure, fail-closed eligibility decisions for automatic assignment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from django.conf import settings

from apps.integrations.hubspot.user_availability import AvailabilityObservation


class EligibilityReason(StrEnum):
    """Stable reason codes used by persistence, telemetry, and diagnostics."""

    ELIGIBLE = "eligible"
    RUNTIME_NOT_AUTHORITATIVE = "runtime_not_authoritative"
    AGENT_INACTIVE = "agent_inactive"
    AUTO_ASSIGN_DISABLED = "auto_assign_disabled"
    MISSING_IDENTITY = "missing_identity"
    MISSING_OBSERVATION = "missing_observation"
    STALE_OBSERVATION = "stale_observation"
    REMOTE_AWAY = "remote_away"
    UNKNOWN_REMOTE_STATUS = "unknown_remote_status"
    ACTIVE_OUT_OF_OFFICE = "active_out_of_office"
    OUTSIDE_WORKING_HOURS = "outside_working_hours"
    STABILIZING = "stabilizing"
    AT_CAPACITY = "at_capacity"
    MALFORMED_REMOTE_DATA = "malformed_remote_data"


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """One deterministic eligibility result."""

    eligible: bool
    reason: EligibilityReason

    @property
    def state(self) -> str:
        """Return the persisted eligibility state."""
        return "eligible" if self.eligible else "ineligible"


_DAY_GROUPS: dict[str, set[int]] = {
    "MONDAY_TO_FRIDAY": {0, 1, 2, 3, 4},
    "SATURDAY_SUNDAY": {5, 6},
    "EVERY_DAY": set(range(7)),
    "MONDAY": {0},
    "TUESDAY": {1},
    "WEDNESDAY": {2},
    "THURSDAY": {3},
    "FRIDAY": {4},
    "SATURDAY": {5},
    "SUNDAY": {6},
}


def evaluate_observation_signals(
    observation: AvailabilityObservation,
    now: datetime,
    *,
    within_working_hours: bool | None = None,
) -> EligibilityDecision:
    """Evaluate HubSpot presence/absence with an optional local schedule veto."""
    if not observation.hubspot_user_id:
        return EligibilityDecision(False, EligibilityReason.MISSING_IDENTITY)
    if observation.availability_status == "away":
        return EligibilityDecision(False, EligibilityReason.REMOTE_AWAY)
    if observation.availability_status != "available":
        return EligibilityDecision(False, EligibilityReason.UNKNOWN_REMOTE_STATUS)
    if any(interval.start_at <= now < interval.end_at for interval in observation.out_of_office_hours):
        return EligibilityDecision(False, EligibilityReason.ACTIVE_OUT_OF_OFFICE)

    if within_working_hours is None:
        if observation.timezone_name is None or not observation.working_hours:
            return EligibilityDecision(False, EligibilityReason.MALFORMED_REMOTE_DATA)
        local_now = now.astimezone(ZoneInfo(observation.timezone_name))
        minute = local_now.hour * 60 + local_now.minute
        within_hours = any(
            local_now.weekday() in _DAY_GROUPS.get(window.days, set())
            and window.start_minute <= minute < window.end_minute
            for window in observation.working_hours
        )
    else:
        within_hours = within_working_hours
    if not within_hours:
        return EligibilityDecision(False, EligibilityReason.OUTSIDE_WORKING_HOURS)
    return EligibilityDecision(True, EligibilityReason.ELIGIBLE)


def evaluate_persisted_agent(agent, now: datetime) -> EligibilityDecision:
    """Re-evaluate an Agent snapshot immediately before reservation."""
    if agent.is_active is False:
        return EligibilityDecision(False, EligibilityReason.AGENT_INACTIVE)
    if not agent.auto_assign_enabled:
        return EligibilityDecision(False, EligibilityReason.AUTO_ASSIGN_DISABLED)
    if not agent.hubspot_user_id:
        return EligibilityDecision(False, EligibilityReason.MISSING_IDENTITY)
    if not agent.availability_observed_at:
        return EligibilityDecision(False, EligibilityReason.MISSING_OBSERVATION)
    freshness = timedelta(seconds=int(settings.AVAILABILITY_FRESHNESS_SECONDS))
    if agent.availability_observed_at < now - freshness:
        return EligibilityDecision(False, EligibilityReason.STALE_OBSERVATION)
    if agent.eligibility_state != "eligible":
        try:
            reason = EligibilityReason(agent.eligibility_reason)
        except ValueError:
            reason = EligibilityReason.MALFORMED_REMOTE_DATA
        return EligibilityDecision(False, reason)
    if agent.current_simultaneous_chats >= (agent.max_simultaneous_chats or 5):
        return EligibilityDecision(False, EligibilityReason.AT_CAPACITY)
    return EligibilityDecision(True, EligibilityReason.ELIGIBLE)
