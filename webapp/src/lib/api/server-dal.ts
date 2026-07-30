import "server-only";

import { cookies } from "next/headers";

import { backendFetch, parseJsonResponse } from "@/src/lib/backend";
import { readAuthTokens } from "@/src/lib/auth/server-session";
import { normalizePaginatedResponse } from "@/src/lib/api/pagination";
import {
  readAgentsAdminOverview,
  readAutoAssignmentOverview,
  readDashboardOverview,
  readMetricsOverview,
  type OverviewReader,
} from "@/src/lib/api/overview-loaders";
import type {
  Agent,
  AgentDailyTimeLog,
  AgentMetricsRow,
  AgentMetricsSummary,
  BusinessHoursResponse,
  ConversationReassignment,
  DailyReport,
  HealthResponse,
  PaginatedResponse,
  QueueHealthResponse,
  QueueMetric,
  QueueStatusResponse,
  ReassignmentSummaryRow,
  SpecialSchedule,
} from "@/src/types/api";

interface QueryValue {
  [key: string]: boolean | number | string | undefined;
}

function withQuery(path: string, query?: QueryValue): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const serialized = params.toString();
  return serialized ? `${path}?${serialized}` : path;
}

async function read<T>(path: string, query?: QueryValue): Promise<T> {
  const tokenStore = await cookies();
  const { accessToken } = readAuthTokens(tokenStore);
  if (!accessToken) throw new Error("Sessao sem access token para leitura server-side.");

  const response = await backendFetch(withQuery(path, query), {}, accessToken);
  if (!response.ok) throw new Error(`Judah respondeu ${response.status} para leitura server-side.`);
  const payload = await parseJsonResponse<T>(response);
  if (payload === null) throw new Error("Judah retornou uma resposta vazia.");
  return payload;
}

async function readPaginated<T>(path: string, query?: QueryValue): Promise<PaginatedResponse<T>> {
  const payload = await read<unknown>(path, query);
  return normalizePaginatedResponse<T>(payload, { path, query });
}

const serverReader: OverviewReader = {
  getHealth: () => read<HealthResponse>("/health/"),
  getQueueStatus: () => read<QueueStatusResponse>("/support/queue/status/"),
  getQueueHealth: () => read<QueueHealthResponse>("/support/queue/health/"),
  getBusinessHours: () => read<BusinessHoursResponse>("/support/business-hours/"),
  listSpecialSchedules: () => read<SpecialSchedule[]>("/support/special-schedules/"),
  listQueueMetrics: (query) => readPaginated<QueueMetric>("/support/queue/metrics/", query),
  listReports: (query) => readPaginated<DailyReport>("/analytics/reports/", query),
  listAgents: (query) => readPaginated<Agent>("/support/agents/", query),
  getAgentMetricsSummary: (query) => read<AgentMetricsSummary>("/support/metrics/agents/summary/", query),
  listReassignments: (query) => readPaginated<ConversationReassignment>("/support/reassignments/", query),
  listAgentMetrics: (query) => readPaginated<AgentMetricsRow>("/support/metrics/agents/", query),
  listAllTimeLogs: (query) => readPaginated<AgentDailyTimeLog>("/support/time-logs/", query),
  getReassignmentsSummary: (query) => read<ReassignmentSummaryRow[]>("/support/reassignments/summary/", query),
};

export const getDashboardSnapshot = () => readDashboardOverview(serverReader);
export const getAutoAssignmentSnapshot = () => readAutoAssignmentOverview(serverReader);
export const getMetricsSnapshot = () => readMetricsOverview(serverReader);
export const getAgentsSnapshot = () => readAgentsAdminOverview(serverReader);
