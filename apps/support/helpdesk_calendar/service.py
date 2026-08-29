"""Deterministic helpdesk calendar resolution and rule persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.support.models import (
    BusinessHoursConfig,
    HelpdeskAbsenceMessage,
    HelpdeskSchedule,
    HelpdeskScheduleInterval,
    HelpdeskScheduleRule,
)
from apps.support.schemas import HelpdeskCalendarRuleRequest
from common.exceptions import ConflictError, NotFoundError, ValidationError

DEFAULT_TIMEZONE = "America/Sao_Paulo"


@dataclass(slots=True)
class _LegacyResolutionContext:
    """Lazily load legacy calendar rows once for a bounded resolution cycle."""

    start: date
    end: date
    loaded: bool = False
    specials_by_date: dict[date, Any] = field(default_factory=dict)
    business_hours_config: BusinessHoursConfig | None = None

    def load(self) -> None:
        """Load legacy fallbacks only if a native rule does not match."""
        if self.loaded:
            return
        from apps.support.models import SpecialSchedule

        self.specials_by_date = {
            item.date: item for item in SpecialSchedule.objects.filter(date__range=(self.start, self.end))
        }
        self.business_hours_config = BusinessHoursConfig.objects.filter(is_active=True).first()
        self.loaded = True


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError(f"Unknown IANA timezone: {name}") from exc


def get_schedule(*, create: bool = False) -> HelpdeskSchedule:
    """Return the published schedule without mutating state during reads."""
    schedule = HelpdeskSchedule.objects.filter(status=HelpdeskSchedule.Status.PUBLISHED).first()
    if schedule:
        return schedule
    if create:
        return HelpdeskSchedule.objects.create(timezone_name=DEFAULT_TIMEZONE)
    # UUID defaults are assigned at construction time; force ``id=None`` so
    # callers can reliably distinguish this read-only fallback from persistence.
    return HelpdeskSchedule(id=None, timezone_name=DEFAULT_TIMEZONE)


def get_active_rules(schedule: HelpdeskSchedule) -> list[HelpdeskScheduleRule]:
    """Return active rules with all relations needed by calendar resolution.

    The cache lives only on the schedule instance, so one request or heartbeat
    cycle cannot repeatedly fetch the same rules and intervals.
    """
    cached = getattr(schedule, "_active_rules_cache", None)
    if cached is not None:
        return cached
    if not schedule.pk:
        rules: list[HelpdeskScheduleRule] = []
    else:
        rules = list(
            schedule.rules.filter(is_active=True).select_related("absence_message").prefetch_related("intervals")
        )
    schedule._active_rules_cache = rules
    return rules


def _rule_matches(rule: HelpdeskScheduleRule, day: date) -> bool:
    if not rule.is_active or day < rule.starts_on or (rule.ends_on and day > rule.ends_on):
        return False
    weekdays = {int(value) for value in rule.weekdays}
    dates = {date.fromisoformat(str(value)) for value in rule.dates}
    if rule.recurrence == HelpdeskScheduleRule.Recurrence.ONCE:
        return day in dates or (not dates and day == rule.starts_on)
    if rule.recurrence == HelpdeskScheduleRule.Recurrence.WEEKLY:
        return day.weekday() in weekdays
    if rule.recurrence == HelpdeskScheduleRule.Recurrence.MONTHLY:
        if weekdays and day.weekday() not in weekdays:
            return False
        return rule.week_of_month is None or ((day.day - 1) // 7 + 1) == rule.week_of_month
    if not dates:
        return day.month == rule.starts_on.month and day.day == rule.starts_on.day
    return any(item.month == day.month and item.day == day.day for item in dates)


def _intervals_for(rule: HelpdeskScheduleRule, day: date) -> list[dict[str, str]]:
    intervals = list(rule.intervals.all())
    selected = [item for item in intervals if item.date == day or item.weekday == day.weekday()]
    if not selected:
        selected = [item for item in intervals if item.date is None and item.weekday is None]
    return [{"start": item.start.strftime("%H:%M"), "end": item.end.strftime("%H:%M")} for item in selected]


def _legacy_resolution(
    day: date,
    *,
    context: _LegacyResolutionContext | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    """Resolve the legacy tables while the native calendar is rolling out."""
    from apps.ai_agents.utils.business_rules import HOLIDAYS, WEEKLY_BUSINESS_HOURS
    from apps.support.models import SpecialSchedule

    if context is None:
        special = SpecialSchedule.objects.filter(date=day).first()
        config = BusinessHoursConfig.objects.filter(is_active=True).first()
    else:
        context.load()
        special = context.specials_by_date.get(day)
        config = context.business_hours_config
    if special:
        if special.schedule_type == SpecialSchedule.ScheduleType.CLOSED:
            return [], special.reason or "special_schedule_closed"
        if special.start_hour is not None and special.end_hour is not None:
            return [
                {
                    "start": f"{special.start_hour:02d}:00",
                    "end": f"{special.end_hour:02d}:00",
                }
            ], special.reason or None
    if day in HOLIDAYS:
        return [], f"holiday:{HOLIDAYS[day]}"

    configured = config.get_hours_for_weekday(day.weekday()) if config else None
    if configured:
        start, end = time(configured[0]), time(configured[1])
        if day.weekday() <= 4 and configured == (9, 18):
            start, end = WEEKLY_BUSINESS_HOURS[day.weekday()]
    elif config:
        return [], "legacy_business_hours_closed"
    else:
        start, end = WEEKLY_BUSINESS_HOURS[day.weekday()]

    intervals = [{"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}]
    if day.weekday() == 3 and start < time(12) and end > time(13):
        intervals = [
            {"start": start.strftime("%H:%M"), "end": "12:00"},
            {"start": "13:00", "end": end.strftime("%H:%M")},
        ]
    return intervals, None


def _plain_message(markdown: str) -> str:
    """Derive a provider-neutral plain text fallback from limited Markdown."""
    value = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", markdown)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    return value.strip()


def resolve_day(
    day: date,
    *,
    schedule: HelpdeskSchedule | None = None,
    rules: list[HelpdeskScheduleRule] | None = None,
    legacy_context: _LegacyResolutionContext | None = None,
) -> dict[str, Any]:
    """Resolve one local calendar date using absence then priority precedence."""
    current = schedule or get_schedule()
    active_rules = rules if rules is not None else get_active_rules(current)
    matching = [rule for rule in active_rules if _rule_matches(rule, day)]
    absences = [rule for rule in matching if rule.rule_type == HelpdeskScheduleRule.RuleType.ABSENCE]
    chosen = sorted(absences or matching, key=lambda item: (-item.priority, str(item.id)))
    if chosen:
        rule = chosen[0]
        message = getattr(getattr(rule, "absence_message", None), "rich_text", None)
        intervals = [] if rule.rule_type == HelpdeskScheduleRule.RuleType.ABSENCE else _intervals_for(rule, day)
        return {
            "date": day,
            "state": "ABSENCE" if rule.rule_type == "absence" else ("OPEN" if intervals else "CLOSED"),
            "intervals": intervals,
            "reason": rule.name,
            "message": message,
            "source_rule_id": rule.id,
            "source_rule_name": rule.name,
            "priority": rule.priority,
        }
    intervals, reason = _legacy_resolution(day, context=legacy_context)
    return {
        "date": day,
        "state": "OPEN" if intervals else "CLOSED",
        "intervals": intervals,
        "reason": reason,
        "message": None,
        "source_rule_id": None,
        "source_rule_name": None,
        "priority": None,
    }


def resolve_range(start: date, end: date) -> tuple[HelpdeskSchedule, list[dict[str, Any]], bool]:
    """Resolve an inclusive date range, failing closed on malformed windows."""
    if end < start or (end - start).days > 366:
        raise ValidationError("Calendar range must be ordered and no longer than 366 days.")
    schedule = get_schedule()
    try:
        _tz(schedule.timezone_name)
        rules = get_active_rules(schedule)
        legacy_context = _LegacyResolutionContext(start=start, end=end)
        return (
            schedule,
            [
                resolve_day(
                    start + timedelta(days=offset),
                    schedule=schedule,
                    rules=rules,
                    legacy_context=legacy_context,
                )
                for offset in range((end - start).days + 1)
            ],
            False,
        )
    except ValueError, ZoneInfoNotFoundError, ValidationError:
        return (
            schedule,
            [
                {
                    "date": start + timedelta(days=offset),
                    "state": "CLOSED",
                    "intervals": [],
                    "reason": "calendar_degraded",
                    "message": None,
                    "source_rule_id": None,
                    "source_rule_name": None,
                    "priority": None,
                }
                for offset in range((end - start).days + 1)
            ],
            True,
        )


def resolve_now(now: datetime | None = None) -> dict[str, Any]:
    """Resolve the current operational state and active local interval."""
    schedule = get_schedule()
    instant = now or timezone.now()
    local = (
        instant.astimezone(_tz(schedule.timezone_name))
        if instant.tzinfo
        else instant.replace(tzinfo=_tz(schedule.timezone_name))
    )
    resolution = resolve_day(local.date(), schedule=schedule)
    current = local.time().replace(tzinfo=None)
    active = any(
        time.fromisoformat(item["start"]) <= current < time.fromisoformat(item["end"])
        for item in resolution["intervals"]
    )
    result = {**resolution, "is_open_now": resolution["state"] == "OPEN" and active}
    from apps.ai_agents.utils.business_rules import is_quinta_fire

    if not result["is_open_now"] and is_quinta_fire(local) and not resolution["source_rule_id"]:
        result["reason"] = "quinta_fire"
    if resolution["state"] == "ABSENCE":
        result["reason"] = f"absence:{resolution['reason']}"
    elif not result["is_open_now"] and not result["reason"]:
        result["reason"] = "off_hours"
    return result


def serialize_rule(rule: HelpdeskScheduleRule) -> dict[str, Any]:
    """Return the stable WebApp rule contract."""
    message = getattr(getattr(rule, "absence_message", None), "rich_text", None)
    return {
        "id": rule.id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "recurrence": rule.recurrence,
        "starts_on": rule.starts_on,
        "ends_on": rule.ends_on,
        "weekdays": rule.weekdays,
        "week_of_month": rule.week_of_month,
        "dates": rule.dates,
        "intervals": _intervals_for(rule, rule.starts_on),
        "message": message,
        "priority": rule.priority,
        "is_active": rule.is_active,
        "version": rule.version,
    }


def save_rule(
    payload: HelpdeskCalendarRuleRequest, *, rule_id: str | None = None, expected_version: int | None = None
) -> HelpdeskScheduleRule:
    """Create or update a rule and atomically advance the published version."""
    with transaction.atomic():
        schedule = get_schedule(create=True)
        rule = HelpdeskScheduleRule.objects.select_for_update().filter(id=rule_id).first() if rule_id else None
        is_new = rule is None
        if rule_id and rule is None:
            raise NotFoundError("Calendar rule not found.")
        if rule and expected_version is not None and rule.version != expected_version:
            raise ConflictError("Calendar rule was changed by another user.")
        if rule is None:
            rule = HelpdeskScheduleRule(schedule=schedule)
        for field in (
            "name",
            "rule_type",
            "recurrence",
            "starts_on",
            "ends_on",
            "weekdays",
            "week_of_month",
            "priority",
        ):
            setattr(rule, field, getattr(payload, field))
        rule.dates = [item.isoformat() for item in payload.dates]
        rule.version = 1 if is_new else rule.version + 1
        rule.full_clean()
        rule.save()
        rule.intervals.all().delete()
        HelpdeskScheduleInterval.objects.bulk_create(
            [HelpdeskScheduleInterval(rule=rule, start=item.start, end=item.end) for item in payload.intervals]
        )
        if payload.rule_type == "absence":
            markdown = payload.message or ""
            HelpdeskAbsenceMessage.objects.update_or_create(
                rule=rule,
                defaults={"rich_text": markdown, "plain_text": _plain_message(markdown)},
            )
        else:
            HelpdeskAbsenceMessage.objects.filter(rule=rule).delete()
        HelpdeskSchedule.objects.filter(pk=schedule.pk).update(version=schedule.version + 1, updated_at=timezone.now())
        return rule


def deactivate_rule(rule_id: str, *, expected_version: int | None = None) -> None:
    """Deactivate a rule after checking its optimistic version."""
    with transaction.atomic():
        rule = HelpdeskScheduleRule.objects.select_for_update().filter(id=rule_id).first()
        if rule is None:
            raise NotFoundError("Calendar rule not found.")
        if expected_version is not None and rule.version != expected_version:
            raise ConflictError("Calendar rule was changed by another user.")
        rule.is_active = False
        rule.version += 1
        rule.save(update_fields=["is_active", "version", "updated_at"])
        HelpdeskSchedule.objects.filter(pk=rule.schedule_id).update(version=F("version") + 1, updated_at=timezone.now())
