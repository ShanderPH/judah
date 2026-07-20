"""Typed normalization for HubSpot user availability properties."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AvailabilityParseError(ValueError):
    """Raised when a HubSpot availability property cannot be trusted."""


class WorkingHoursWindow(BaseModel):
    """One HubSpot working-hours window."""

    model_config = ConfigDict(populate_by_name=True)

    days: str
    start_minute: int = Field(alias="startMinute", ge=0, le=1440)
    end_minute: int = Field(alias="endMinute", ge=0, le=1440)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Reject empty or reversed working-hour intervals."""
        if self.start_minute >= self.end_minute:
            raise ValueError("startMinute must be earlier than endMinute")
        return self


class OutOfOfficeInterval(BaseModel):
    """One normalized HubSpot out-of-office interval."""

    model_config = ConfigDict(populate_by_name=True)

    start_at: datetime = Field(alias="startTimestamp")
    end_at: datetime = Field(alias="endTimestamp")

    @field_validator("start_at", "end_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: Any) -> datetime:
        """Accept HubSpot epoch variants and ISO timestamps as UTC."""
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str) and not value.strip().isdigit():
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

        numeric = float(value)
        absolute = abs(numeric)
        if absolute >= 1_000_000_000_000:
            numeric /= 1000
        elif absolute >= 10_000_000_000:
            # The current HubSpot Users API guide contains decisecond examples.
            numeric /= 10
        return datetime.fromtimestamp(numeric, tz=UTC)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Reject empty or reversed absence intervals."""
        if self.start_at >= self.end_at:
            raise ValueError("startTimestamp must be earlier than endTimestamp")
        return self


class AvailabilityObservation(BaseModel):
    """Normalized, hashable observation from the HubSpot Users API."""

    hubspot_user_id: str
    email: str
    availability_status: str
    out_of_office_hours: list[OutOfOfficeInterval]
    working_hours: list[WorkingHoursWindow]
    timezone_name: str | None
    observed_at: datetime
    raw_state_hash: str

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        """Validate an optional remote IANA timezone."""
        if not value:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("invalid IANA timezone") from exc
        return value


def _decode_json_array(raw: Any, *, required: bool, field_name: str) -> list[dict[str, Any]]:
    if raw in (None, ""):
        if required:
            raise AvailabilityParseError(f"missing_{field_name}")
        return []
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, list):
        raise AvailabilityParseError(f"invalid_{field_name}")
    return value


def normalize_availability_item(
    item: dict[str, Any],
    observed_at: datetime,
    *,
    require_remote_schedule: bool = True,
) -> AvailabilityObservation:
    """Convert one HubSpot client result into a validated observation."""
    raw_state = {
        "user_id": item.get("user_id"),
        "availability_status": item.get("availability_status"),
        "out_of_office_hours": item.get("out_of_office_hours"),
        "working_hours": item.get("working_hours"),
        "timezone": item.get("timezone"),
    }
    raw_hash = hashlib.sha256(
        json.dumps(raw_state, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    try:
        out_of_office = [
            OutOfOfficeInterval.model_validate(value)
            for value in _decode_json_array(
                item.get("out_of_office_hours"),
                required=False,
                field_name="out_of_office_hours",
            )
        ]
        working_hours = [
            WorkingHoursWindow.model_validate(value)
            for value in _decode_json_array(
                item.get("working_hours"),
                required=require_remote_schedule,
                field_name="working_hours",
            )
        ]
        timezone_name = str(item.get("timezone") or "").strip() or None
        if require_remote_schedule and timezone_name is None:
            raise AvailabilityParseError("missing_timezone")
        return AvailabilityObservation(
            hubspot_user_id=str(item.get("user_id") or ""),
            email=str(item.get("email") or "").strip().lower(),
            availability_status=str(item.get("availability_status") or "").strip().lower(),
            out_of_office_hours=out_of_office,
            working_hours=working_hours,
            timezone_name=timezone_name,
            observed_at=observed_at,
            raw_state_hash=raw_hash,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, AvailabilityParseError):
            raise
        raise AvailabilityParseError("malformed_availability_payload") from exc
