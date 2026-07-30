import { describe, expect, it } from "vitest";

import { normalizePaginatedResponse } from "@/src/lib/api/client";
import { readDashboardOverview, type OverviewReader } from "@/src/lib/api/overview-loaders";

const emptyPage = { count: 0, next: null, previous: null, results: [] };

function createReader(): OverviewReader {
  return {
    getHealth: async () => ({ status: "healthy", timestamp: "2026-07-29T00:00:00Z", version: "test", checks: { database: "ok" } }),
    getQueueStatus: async () => ({ online_agents: 1, eligible_agents: 1, pending_queue_depth: 2, agents: [] }),
    getQueueHealth: async () => ({
      timestamp: "2026-07-29T00:00:00Z",
      summary: { total_agents: 1, online_agents: 1, away_agents: 0, eligible_agents: 1, pending_queue_depth: 2, system_ok: true, warnings: [], issues: [] },
      absent_agents: [], eligible_agents: [], pending_tickets: [], last_assignments: [],
    }),
    getBusinessHours: async () => ({ name: "Padrao", is_active: true, monday: "", tuesday: "", wednesday: "", thursday: "", friday: "", saturday: "", sunday: "", timezone_name: "America/Sao_Paulo", is_currently_business_hours: true }),
    listSpecialSchedules: async () => [],
    listQueueMetrics: async () => emptyPage,
    listReports: async () => { throw new Error("analytics unavailable"); },
    listAgents: async () => emptyPage,
    getAgentMetricsSummary: async () => ({ period_days: 7, total_agents_with_data: 0, total_chats: 0, total_chats_closed: 0, avg_handle_time_min: 0, avg_first_response_min: 0, avg_resolution_rate: 0, avg_csat: 0 }),
    listReassignments: async () => emptyPage,
    listAgentMetrics: async () => emptyPage,
    listAllTimeLogs: async () => emptyPage,
    getReassignmentsSummary: async () => [],
  };
}

describe("Gate E data contracts", () => {
  it("preserves backend pagination links instead of fabricating null navigation", () => {
    const page = normalizePaginatedResponse({ count: 120, next: "/items?limit=40&offset=40", previous: null, results: [1] });
    expect(page).toEqual({ count: 120, next: "/items?limit=40&offset=40", previous: null, results: [1] });
  });

  it("normalizes the Django Ninja items envelope and derives offset navigation", () => {
    const firstPage = normalizePaginatedResponse<number>(
      { count: 120, items: [1] },
      { path: "/items", query: { limit: 40, offset: 0 } },
    );
    const secondPage = normalizePaginatedResponse<number>(
      { count: 120, items: [2] },
      { path: "/items", query: { limit: 40, offset: 40 } },
    );

    expect(firstPage).toEqual({
      count: 120,
      next: "/items?limit=40&offset=40",
      previous: null,
      results: [1],
    });
    expect(secondPage).toEqual({
      count: 120,
      next: "/items?limit=40&offset=80",
      previous: "/items?limit=40&offset=0",
      results: [2],
    });
  });

  it("rejects malformed pagination so overview degradation can handle it", () => {
    expect(() => normalizePaginatedResponse({ count: 1 })).toThrow(
      "expected results or items array",
    );
  });

  it("keeps health and queue available when analytics fails", async () => {
    const snapshot = await readDashboardOverview(createReader());
    expect(snapshot.health.status).toBe("healthy");
    expect(snapshot.queueStatus.pending_queue_depth).toBe(2);
    expect(snapshot.degradedServices).toEqual(["analytics-reports"]);
    expect(snapshot.latestReport).toBeNull();
  });
});
