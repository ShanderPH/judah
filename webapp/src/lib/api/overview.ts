"use client";

import { judahApi } from "@/src/lib/api/client";
import {
  readAgentsAdminOverview,
  readAutoAssignmentOverview,
  readDashboardOverview,
  readMetricsOverview,
  type OverviewReader,
} from "@/src/lib/api/overview-loaders";

function reader(signal?: AbortSignal): OverviewReader {
  const options = signal ? { signal } : undefined;
  return {
    ...judahApi,
    getHealth: () => judahApi.getHealth(options),
    getQueueStatus: () => judahApi.getQueueStatus(options),
    getQueueHealth: () => judahApi.getQueueHealth(options),
    getBusinessHours: () => judahApi.getBusinessHours(options),
    listSpecialSchedules: () => judahApi.listSpecialSchedules(options),
    listQueueMetrics: (query) => judahApi.listQueueMetrics(query, options),
    listReports: (query) => judahApi.listReports(query, options),
    listAgents: (query) => judahApi.listAgents(query, options),
    getAgentMetricsSummary: (query) => judahApi.getAgentMetricsSummary(query, options),
    listReassignments: (query) => judahApi.listReassignments(query, options),
    listAgentMetrics: (query) => judahApi.listAgentMetrics(query, options),
    listAllTimeLogs: (query) => judahApi.listAllTimeLogs(query, options),
    getReassignmentsSummary: (query) => judahApi.getReassignmentsSummary(query, options),
  };
}

export const loadDashboardOverview = (signal?: AbortSignal) => readDashboardOverview(reader(signal));
export const loadAutoAssignmentOverview = (signal?: AbortSignal) => readAutoAssignmentOverview(reader(signal));
export const loadMetricsOverview = (signal?: AbortSignal) => readMetricsOverview(reader(signal));
export const loadAgentsAdminOverview = (signal?: AbortSignal) => readAgentsAdminOverview(reader(signal));
