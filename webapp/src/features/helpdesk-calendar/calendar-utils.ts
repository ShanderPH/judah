import type {
  HelpdeskCalendarInterval,
  HelpdeskCalendarOccurrence,
} from "@/src/types/api";

export type CalendarView = "month" | "week";

export function isoDate(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function monthDays(cursor: Date): Date[] {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return day;
  });
}

export function weekDays(cursor: Date): Date[] {
  const start = new Date(cursor);
  start.setDate(cursor.getDate() - cursor.getDay());
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return day;
  });
}

export function occurrenceFor(occurrences: HelpdeskCalendarOccurrence[], date: Date) {
  return occurrences.find((item) => item.date === isoDate(date));
}

export function areCalendarIntervalsValid(intervals: HelpdeskCalendarInterval[]): boolean {
  if (!intervals.length) return false;
  const ordered = [...intervals].sort((left, right) => left.start.localeCompare(right.start));
  return ordered.every(
    (interval, index) =>
      interval.start < interval.end &&
      (index === 0 || interval.start >= ordered[index - 1].end),
  );
}

export function periodLabel(cursor: Date, view: CalendarView): string {
  if (view === "week") {
    const days = weekDays(cursor);
    return `${days[0].toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })} — ${days[6].toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" })}`;
  }
  return cursor.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
}

export function shiftPeriod(cursor: Date, view: CalendarView, amount: number): Date {
  const next = new Date(cursor);
  if (view === "week") next.setDate(next.getDate() + amount * 7);
  else next.setMonth(next.getMonth() + amount);
  return next;
}
