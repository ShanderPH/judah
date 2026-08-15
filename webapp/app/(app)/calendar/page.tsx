import type { Metadata } from "next";
import { HelpdeskCalendarView } from "@/src/features/helpdesk-calendar/helpdesk-calendar-view";

export const metadata: Metadata = { title: "Calendário Helpdesk | Judah" };

export default function CalendarPage() {
  return <HelpdeskCalendarView />;
}
