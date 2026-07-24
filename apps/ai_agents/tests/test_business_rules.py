"""Unit tests for the business rules engine (pure functions, no DB)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from apps.ai_agents.utils.business_rules import (
    HOLIDAYS,
    SAO_PAULO_TZ,
    holiday_name,
    is_business_hours,
    is_holiday,
    is_quinta_fire,
    now_sao_paulo,
    off_hours_reason,
)


class TestNowSaoPaulo:
    def test_returns_tz_aware_datetime(self) -> None:
        now = now_sao_paulo()
        assert now.tzinfo is not None
        assert now.tzinfo.key == "America/Sao_Paulo"


class TestIsQuintaFire:
    def test_thursday_noon_is_quinta_fire(self) -> None:
        thursday_noon = datetime(2026, 4, 23, 12, 30, tzinfo=SAO_PAULO_TZ)
        assert is_quinta_fire(thursday_noon) is True

    def test_thursday_start_boundary_inclusive(self) -> None:
        thursday_12_00 = datetime(2026, 4, 23, 12, 0, tzinfo=SAO_PAULO_TZ)
        assert is_quinta_fire(thursday_12_00) is True

    def test_thursday_end_boundary_exclusive(self) -> None:
        thursday_13_00 = datetime(2026, 4, 23, 13, 0, tzinfo=SAO_PAULO_TZ)
        assert is_quinta_fire(thursday_13_00) is False

    def test_non_thursday_returns_false(self) -> None:
        wednesday_noon = datetime(2026, 4, 22, 12, 30, tzinfo=SAO_PAULO_TZ)
        assert is_quinta_fire(wednesday_noon) is False

    def test_thursday_outside_window_returns_false(self) -> None:
        thursday_morning = datetime(2026, 4, 23, 11, 0, tzinfo=SAO_PAULO_TZ)
        assert is_quinta_fire(thursday_morning) is False


class TestIsBusinessHours:
    def test_weekday_morning_in_hours(self) -> None:
        # Wednesday (Apr 22) at 10:00 — weekday, inside 09-18 window.
        wed = datetime(2026, 4, 22, 10, 0, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(wed) is True

    def test_weekday_before_nine_out_of_hours(self) -> None:
        wed = datetime(2026, 4, 22, 8, 59, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(wed) is False

    def test_weekday_after_eighteen_out_of_hours(self) -> None:
        wed = datetime(2026, 4, 22, 18, 0, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(wed) is False

    def test_weekday_closing_boundary_is_17_50(self) -> None:
        before_close = datetime(2026, 4, 22, 17, 49, 59, tzinfo=SAO_PAULO_TZ)
        at_close = datetime(2026, 4, 22, 17, 50, tzinfo=SAO_PAULO_TZ)

        assert is_business_hours(before_close) is True
        assert is_business_hours(at_close) is False

    def test_saturday_in_window(self) -> None:
        sat = datetime(2026, 4, 25, 10, 0, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(sat) is True

    def test_saturday_out_of_window(self) -> None:
        sat = datetime(2026, 4, 25, 13, 0, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(sat) is False

    def test_sunday_in_window(self) -> None:
        sun = datetime(2026, 4, 26, 9, 0, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(sun) is True

    def test_sunday_out_of_window(self) -> None:
        sun = datetime(2026, 4, 26, 12, 0, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(sun) is False

    def test_holiday_returns_false_even_during_hours(self) -> None:
        # Apr 21 2026 is Tiradentes (Tuesday).
        holiday = datetime(2026, 4, 21, 10, 0, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(holiday) is False

    def test_quinta_fire_returns_false(self) -> None:
        thursday_noon = datetime(2026, 4, 23, 12, 30, tzinfo=SAO_PAULO_TZ)
        assert is_business_hours(thursday_noon) is False

    def test_naive_datetime_treated_as_sao_paulo(self) -> None:
        naive = datetime(2026, 4, 22, 10, 0)
        assert is_business_hours(naive) is True

    def test_utc_aware_datetime_converted(self) -> None:
        # 13:00 UTC on Apr 22 2026 → 10:00 São Paulo.
        utc = datetime(2026, 4, 22, 13, 0, tzinfo=UTC)
        assert is_business_hours(utc) is True


class TestIsHoliday:
    def test_known_holiday(self) -> None:
        # Tiradentes.
        d = datetime(2026, 4, 21, 12, 0, tzinfo=SAO_PAULO_TZ)
        assert is_holiday(d) is True

    def test_non_holiday(self) -> None:
        d = datetime(2026, 4, 22, 12, 0, tzinfo=SAO_PAULO_TZ)
        assert is_holiday(d) is False

    def test_holiday_list_sanity(self) -> None:
        # Independence and Christmas must be present in the hardcoded list.
        assert date(2026, 9, 7) in HOLIDAYS
        assert date(2026, 12, 25) in HOLIDAYS


class TestHolidayName:
    def test_returns_name_for_holiday(self) -> None:
        d = datetime(2026, 4, 21, 12, 0, tzinfo=SAO_PAULO_TZ)
        assert holiday_name(d) == "Tiradentes"

    def test_returns_none_for_non_holiday(self) -> None:
        d = datetime(2026, 4, 22, 12, 0, tzinfo=SAO_PAULO_TZ)
        assert holiday_name(d) is None


class TestOffHoursReason:
    def test_in_business_hours_returns_none(self) -> None:
        d = datetime(2026, 4, 22, 10, 0, tzinfo=SAO_PAULO_TZ)
        assert off_hours_reason(d) is None

    def test_holiday_reason(self) -> None:
        d = datetime(2026, 4, 21, 10, 0, tzinfo=SAO_PAULO_TZ)
        reason = off_hours_reason(d)
        assert reason is not None
        assert reason.startswith("holiday:")
        assert "Tiradentes" in reason

    def test_quinta_fire_reason(self) -> None:
        d = datetime(2026, 4, 23, 12, 30, tzinfo=SAO_PAULO_TZ)
        assert off_hours_reason(d) == "quinta_fire"

    def test_off_hours_reason_after_six_pm(self) -> None:
        d = datetime(2026, 4, 22, 19, 0, tzinfo=SAO_PAULO_TZ)
        assert off_hours_reason(d) == "off_hours"

    def test_foreign_tz_is_converted(self) -> None:
        # 02:00 UTC on the holiday → 23:00 SP on the previous day (Apr 20).
        utc_midnight = datetime(2026, 4, 21, 2, 0, tzinfo=UTC)
        # Apr 20 2026 is a Monday — should be off_hours, not holiday.
        assert off_hours_reason(utc_midnight) == "off_hours"

    def test_other_timezone_conversion(self) -> None:
        # 14:00 NY (Apr 22) → 15:00 SP (Apr 22) — within business hours.
        ny = datetime(2026, 4, 22, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        assert off_hours_reason(ny) is None
