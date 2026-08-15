"""Focused tests for the published helpdesk calendar resolver."""

from datetime import date, datetime, time
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError

from apps.support.helpdesk_calendar.service import (
    deactivate_rule,
    get_schedule,
    resolve_day,
    resolve_now,
    resolve_range,
    save_rule,
    serialize_rule,
)
from apps.support.models import (
    BusinessHoursConfig,
    HelpdeskAbsenceMessage,
    HelpdeskSchedule,
    HelpdeskScheduleInterval,
    SpecialSchedule,
)
from apps.support.schemas import HelpdeskCalendarIntervalSchema, HelpdeskCalendarRuleRequest
from common.exceptions import ConflictError, NotFoundError, ValidationError


@pytest.mark.django_db
def test_absence_has_precedence_over_service_and_returns_message() -> None:
    service = HelpdeskCalendarRuleRequest(
        name="Weekday service",
        rule_type="service",
        recurrence="weekly",
        starts_on=date(2026, 8, 1),
        weekdays=[0],
        intervals=[HelpdeskCalendarIntervalSchema(start=time(9), end=time(17))],
    )
    absence = HelpdeskCalendarRuleRequest(
        name="Holiday",
        rule_type="absence",
        recurrence="once",
        starts_on=date(2026, 8, 3),
        dates=[date(2026, 8, 3)],
        message="Voltamos amanhã.",
        priority=10,
    )
    save_rule(service)
    save_rule(absence)

    result = resolve_day(date(2026, 8, 3))

    assert result["state"] == "ABSENCE"
    assert result["message"] == "Voltamos amanhã."
    assert result["intervals"] == []


@pytest.mark.django_db
def test_range_uses_legacy_fallback_when_no_rules_exist() -> None:
    _, occurrences, degraded = resolve_range(date(2026, 8, 10), date(2026, 8, 16))

    assert degraded is False
    assert len(occurrences) == 7
    assert occurrences[0]["state"] == "OPEN"


@pytest.mark.django_db
def test_interval_database_constraint_rejects_reversed_bounds() -> None:
    schedule = get_schedule(create=True)
    rule = schedule.rules.create(
        name="Invalid", rule_type="service", recurrence="once", starts_on=date(2026, 8, 1), dates=["2026-08-01"]
    )

    with pytest.raises(IntegrityError):
        HelpdeskScheduleInterval.objects.create(rule=rule, start=time(17), end=time(9))


@pytest.mark.django_db
def test_deactivate_rule_advances_versions_and_invalid_range_fails_closed() -> None:
    payload = HelpdeskCalendarRuleRequest(
        name="Temporary",
        rule_type="service",
        recurrence="once",
        starts_on=date(2026, 8, 10),
        dates=[date(2026, 8, 10)],
        intervals=[HelpdeskCalendarIntervalSchema(start=time(9), end=time(10))],
    )
    rule = save_rule(payload)
    schedule = rule.schedule
    schedule.refresh_from_db()
    version_before_deactivate = schedule.version
    deactivate_rule(str(rule.pk), expected_version=rule.version)
    rule.refresh_from_db()
    schedule.refresh_from_db()

    assert rule.is_active is False
    assert schedule.version == version_before_deactivate + 1
    with pytest.raises(ValidationError):
        resolve_range(date(2026, 8, 2), date(2026, 8, 1))


@pytest.mark.django_db
def test_monthly_and_yearly_rules_and_custom_intervals_resolve() -> None:
    monthly = HelpdeskCalendarRuleRequest(
        name="First Monday",
        rule_type="service",
        recurrence="monthly",
        starts_on=date(2026, 8, 1),
        weekdays=[0],
        week_of_month=1,
        intervals=[HelpdeskCalendarIntervalSchema(start=time(9), end=time(10))],
    )
    yearly = HelpdeskCalendarRuleRequest(
        name="Annual closure",
        rule_type="absence",
        recurrence="yearly",
        starts_on=date(2026, 1, 1),
        dates=[date(2026, 12, 25)],
        message="Fechado no Natal.",
        priority=20,
    )
    save_rule(monthly)
    save_rule(yearly)

    assert resolve_day(date(2026, 8, 3))["state"] == "OPEN"
    assert resolve_day(date(2026, 12, 25))["state"] == "ABSENCE"


@pytest.mark.django_db
def test_calendar_conflicts_and_degraded_resolution_are_explicit() -> None:
    payload = HelpdeskCalendarRuleRequest(
        name="Conflict",
        rule_type="service",
        recurrence="once",
        starts_on=date(2026, 8, 10),
        dates=[date(2026, 8, 10)],
        intervals=[HelpdeskCalendarIntervalSchema(start=time(9), end=time(10))],
    )
    rule = save_rule(payload)
    with pytest.raises(ConflictError):
        save_rule(payload, rule_id=str(rule.pk), expected_version=99)
    with pytest.raises(NotFoundError):
        deactivate_rule("00000000-0000-0000-0000-000000000000")
    schedule = rule.schedule
    schedule.timezone_name = "Invalid/Timezone"
    schedule.save(update_fields=["timezone_name"])
    _, occurrences, degraded = resolve_range(date(2026, 8, 10), date(2026, 8, 10))
    assert degraded is True and occurrences[0]["state"] == "CLOSED"


@pytest.mark.django_db
def test_resolve_now_uses_published_rule_at_boundaries() -> None:
    payload = HelpdeskCalendarRuleRequest(
        name="Current window",
        rule_type="service",
        recurrence="once",
        starts_on=date(2026, 8, 12),
        dates=[date(2026, 8, 12)],
        intervals=[HelpdeskCalendarIntervalSchema(start=time(9), end=time(10))],
    )
    save_rule(payload)
    assert resolve_now(datetime(2026, 8, 12, 9, 30))["is_open_now"] is True
    assert resolve_now(datetime(2026, 8, 12, 10, 0))["is_open_now"] is False


@pytest.mark.django_db
def test_multiple_intervals_preserve_midday_break_and_runtime_authority() -> None:
    payload = HelpdeskCalendarRuleRequest(
        name="Split shift",
        rule_type="service",
        recurrence="once",
        starts_on=date(2026, 8, 12),
        dates=[date(2026, 8, 12)],
        intervals=[
            HelpdeskCalendarIntervalSchema(start=time(9), end=time(12)),
            HelpdeskCalendarIntervalSchema(start=time(13), end=time(17, 50)),
        ],
    )
    save_rule(payload)

    assert resolve_day(date(2026, 8, 12))["intervals"] == [
        {"start": "09:00", "end": "12:00"},
        {"start": "13:00", "end": "17:50"},
    ]
    assert resolve_now(datetime(2026, 8, 12, 12, 30))["is_open_now"] is False
    assert resolve_now(datetime(2026, 8, 12, 13, 1))["is_open_now"] is True


@pytest.mark.django_db
def test_absence_keeps_limited_markdown_and_plain_text_fallback() -> None:
    rule = save_rule(
        HelpdeskCalendarRuleRequest(
            name="Team event",
            rule_type="absence",
            recurrence="once",
            starts_on=date(2026, 8, 14),
            dates=[date(2026, 8, 14)],
            message="Estamos **ausentes** hoje. 😊",
        )
    )

    resolution = resolve_day(date(2026, 8, 14))
    message = HelpdeskAbsenceMessage.objects.get(rule=rule)

    assert resolution["message"] == "Estamos **ausentes** hoje. 😊"
    assert message.plain_text == "Estamos ausentes hoje. 😊"


@pytest.mark.django_db
def test_legacy_data_migration_creates_editable_rules_and_special_override() -> None:
    BusinessHoursConfig.objects.create(name="Production hours", is_active=True)
    SpecialSchedule.objects.create(
        date=date(2026, 8, 17),
        schedule_type=SpecialSchedule.ScheduleType.CLOSED,
        reason="Internal event",
    )
    migration = import_module("apps.support.migrations.0028_helpdeskschedule_helpdeskschedulerule_and_more")

    migration.migrate_legacy_calendar(django_apps, None)

    thursday = resolve_day(date(2026, 8, 13))
    special = resolve_day(date(2026, 8, 17))
    assert thursday["source_rule_id"] is not None
    assert thursday["intervals"] == [
        {"start": "09:00", "end": "12:00"},
        {"start": "13:00", "end": "17:50"},
    ]
    assert special["state"] == "ABSENCE"
    assert special["source_rule_name"] == "Exceção legada — Internal event"


@pytest.mark.django_db
def test_unsaved_schedule_resolves_legacy_exceptions_and_disabled_day() -> None:
    HelpdeskSchedule.objects.all().delete()
    schedule = get_schedule()
    assert schedule.pk is None

    SpecialSchedule.objects.create(
        date=date(2026, 8, 19),
        schedule_type=SpecialSchedule.ScheduleType.CLOSED,
        reason="Team event",
    )
    SpecialSchedule.objects.create(
        date=date(2026, 8, 18),
        schedule_type=SpecialSchedule.ScheduleType.CUSTOM,
        start_hour=10,
        end_hour=15,
        reason="Reduced hours",
    )

    closed = resolve_day(date(2026, 8, 19), schedule=schedule)
    custom = resolve_day(date(2026, 8, 18), schedule=schedule)
    holiday = resolve_day(date(2026, 4, 21), schedule=schedule)

    assert (closed["state"], closed["reason"]) == ("CLOSED", "Team event")
    assert custom["intervals"] == [{"start": "10:00", "end": "15:00"}]
    assert holiday["reason"].startswith("holiday:")

    BusinessHoursConfig.objects.create(
        name="Monday disabled",
        monday_start=9,
        monday_end=9,
    )
    disabled = resolve_day(date(2026, 8, 17), schedule=schedule)
    assert (disabled["state"], disabled["reason"]) == (
        "CLOSED",
        "legacy_business_hours_closed",
    )

    created = get_schedule(create=True)
    assert created.pk is not None


@pytest.mark.django_db
def test_rule_update_serialization_and_optimistic_errors() -> None:
    absence = HelpdeskCalendarRuleRequest(
        name="Editable rule",
        rule_type="absence",
        recurrence="once",
        starts_on=date(2026, 9, 2),
        dates=[date(2026, 9, 2)],
        message="Maintenance",
    )
    rule = save_rule(absence)
    service = HelpdeskCalendarRuleRequest(
        name="Editable rule",
        rule_type="service",
        recurrence="once",
        starts_on=date(2026, 9, 2),
        dates=[date(2026, 9, 2)],
        intervals=[HelpdeskCalendarIntervalSchema(start=time(10), end=time(12))],
    )

    updated = save_rule(
        service,
        rule_id=str(rule.pk),
        expected_version=rule.version,
    )
    serialized = serialize_rule(updated)

    assert serialized["version"] == 2
    assert serialized["intervals"] == [{"start": "10:00", "end": "12:00"}]
    assert not HelpdeskAbsenceMessage.objects.filter(rule=updated).exists()

    with pytest.raises(ConflictError):
        deactivate_rule(str(updated.pk), expected_version=1)
    with pytest.raises(NotFoundError):
        save_rule(
            service,
            rule_id="00000000-0000-0000-0000-000000000000",
        )


@pytest.mark.django_db
def test_interval_selectors_and_annual_rule_without_explicit_dates() -> None:
    schedule = get_schedule(create=True)
    rule = schedule.rules.create(
        name="Weekday-specific intervals",
        rule_type="service",
        recurrence="weekly",
        starts_on=date(2026, 1, 1),
        weekdays=[0, 1],
        priority=500,
    )
    HelpdeskScheduleInterval.objects.create(
        rule=rule,
        weekday=0,
        start=time(9),
        end=time(11),
    )
    HelpdeskScheduleInterval.objects.create(
        rule=rule,
        weekday=1,
        start=time(13),
        end=time(15),
    )
    annual = schedule.rules.create(
        name="Annual service",
        rule_type="service",
        recurrence="yearly",
        starts_on=date(2026, 8, 20),
        priority=600,
    )
    HelpdeskScheduleInterval.objects.create(
        rule=annual,
        start=time(8),
        end=time(9),
    )

    assert resolve_day(date(2026, 8, 17))["intervals"] == [{"start": "09:00", "end": "11:00"}]
    assert resolve_day(date(2027, 8, 20))["source_rule_name"] == "Annual service"
