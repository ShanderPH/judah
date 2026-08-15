import { describe, expect, it } from "vitest";
import {
  areCalendarIntervalsValid,
  isoDate,
  monthDays,
  shiftPeriod,
  weekDays,
} from "@/src/features/helpdesk-calendar/calendar-utils";

describe("helpdesk calendar periods", () => {
  it("creates a stable six-week month grid", () => {
    const days = monthDays(new Date(2026, 7, 12));
    expect(days).toHaveLength(42);
    expect(days[0].getDay()).toBe(0);
    expect(days.some((day) => isoDate(day) === "2026-08-12")).toBe(true);
  });

  it("starts weeks on Sunday and shifts by seven days", () => {
    const days = weekDays(new Date(2026, 7, 12));
    expect(days).toHaveLength(7);
    expect(days[0].getDay()).toBe(0);
    expect(isoDate(shiftPeriod(new Date(2026, 7, 12), "week", 1))).toBe("2026-08-19");
  });

  it("accepts multiple visible intervals and rejects overlap", () => {
    expect(
      areCalendarIntervalsValid([
        { start: "09:00", end: "12:00" },
        { start: "13:00", end: "17:50" },
      ]),
    ).toBe(true);
    expect(
      areCalendarIntervalsValid([
        { start: "09:00", end: "13:30" },
        { start: "13:00", end: "17:50" },
      ]),
    ).toBe(false);
  });
});
