"use client";

import type {
  Agent,
  AgentDailyTimeLog,
  AgentMetricsRow,
  AgentMetricsSummary,
  ApiErrorPayload,
  AssignedConversation,
  AssignmentActionResponse,
  AuthTokens,
  BusinessHoursResponse,
  ConversationReassignment,
  CreateAgentPayload,
  DailyReport,
  ForceReassignPayload,
  HealthResponse,
  ManualAssignPayload,
  PaginatedResponse,
  PendingConversation,
  QueueHealthResponse,
  QueueMetric,
  QueueStatusResponse,
  ReassignmentSummaryRow,
  SessionPayload,
  SpecialSchedule,
  SyncNovoResponse,
  UpdateAgentPayload,
} from "@/src/types/api";

interface LoginPayload {
  identity: string;
  password: string;
}

interface QueryValue {
  [key: string]: boolean | number | string | undefined;
}

export class ApiClientError extends Error {
  status: number;
  detail: string;
  errors?: Record<string, unknown>;
  service?: string;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.detail);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = payload.detail;
    this.errors = payload.errors;
    this.service = payload.service;
  }
}

function buildQuery(params?: QueryValue): string {
  if (!params) {
    return "";
  }

  const query = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") {
      continue;
    }

    query.set(key, String(value));
  }

  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

async function request<T>(
  path: string,
  init?: RequestInit & {
    query?: QueryValue;
  },
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${path}${buildQuery(init?.query)}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    headers,
  });

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) {
    throw new ApiClientError(response.status, (payload as ApiErrorPayload) ?? { detail: "Request failed." });
  }

  return payload as T;
}

// Django Ninja's paginator returns `{items, count}`. The webapp expects the
// DRF-style `{results, count, next, previous}` shape. Normalize at the edge so
// every list endpoint can share the `PaginatedResponse<T>` type without each
// component having to know which envelope it gets.
async function requestPaginated<T>(
  path: string,
  init?: RequestInit & {
    query?: QueryValue;
  },
): Promise<PaginatedResponse<T>> {
  const raw = await request<{ items?: T[]; results?: T[]; count?: number }>(path, init);
  const results = raw.results ?? raw.items ?? [];
  return {
    count: raw.count ?? results.length,
    next: null,
    previous: null,
    results,
  };
}

export const authClient = {
  login: (payload: LoginPayload) =>
    request<SessionPayload>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  logout: () =>
    request<{ ok: true }>("/api/auth/logout", {
      method: "POST",
    }),
  session: () => request<SessionPayload>("/api/auth/session"),
};

export const judahApi = {
  getHealth: () => request<HealthResponse>("/api/backend/health/"),
  getQueueStatus: () => request<QueueStatusResponse>("/api/backend/support/queue/status/"),
  getQueueHealth: () => request<QueueHealthResponse>("/api/backend/support/queue/health/"),
  getBusinessHours: () => request<BusinessHoursResponse>("/api/backend/support/business-hours/"),
  listSpecialSchedules: () => request<SpecialSchedule[]>("/api/backend/support/special-schedules/"),
  syncNovo: () =>
    request<SyncNovoResponse>("/api/backend/support/queue/sync-novo/", {
      method: "POST",
    }),
  listPendingConversations: (params?: QueryValue) =>
    requestPaginated<PendingConversation>("/api/backend/support/queue/pending/", {
      query: params,
    }),
  listAssignedConversations: (params?: QueryValue) =>
    requestPaginated<AssignedConversation>("/api/backend/support/queue/assigned/", {
      query: params,
    }),
  listQueueMetrics: (params?: QueryValue) =>
    requestPaginated<QueueMetric>("/api/backend/support/queue/metrics/", {
      query: params,
    }),
  listReports: (params?: QueryValue) =>
    requestPaginated<DailyReport>("/api/backend/analytics/reports/", {
      query: params,
    }),

  // ----- Agents administration -----
  listAgents: (params?: QueryValue) =>
    requestPaginated<Agent>("/api/backend/support/agents/", { query: params }),
  retrieveAgent: (agentId: string) =>
    request<Agent>(`/api/backend/support/agents/${agentId}`),
  createAgent: (payload: CreateAgentPayload) =>
    request<Agent>("/api/backend/support/agents/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateAgent: (agentId: string, payload: UpdateAgentPayload) =>
    request<Agent>(`/api/backend/support/agents/${agentId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  inactivateAgent: (agentId: string) =>
    request<Agent>(`/api/backend/support/agents/${agentId}/inactivate`, {
      method: "POST",
    }),
  reactivateAgent: (agentId: string) =>
    request<Agent>(`/api/backend/support/agents/${agentId}/reactivate`, {
      method: "POST",
    }),

  // ----- Aggregated reads -----
  listAgentMetrics: (params?: QueryValue) =>
    requestPaginated<AgentMetricsRow>("/api/backend/support/metrics/agents/", {
      query: params,
    }),
  getAgentMetricsSummary: (params?: QueryValue) =>
    request<AgentMetricsSummary>("/api/backend/support/metrics/agents/summary/", {
      query: params,
    }),
  listAgentMetricsForAgent: (agentId: string, params?: QueryValue) =>
    requestPaginated<AgentMetricsRow>(
      `/api/backend/support/agents/${agentId}/metrics/`,
      { query: params },
    ),
  listAgentTimeLogs: (agentId: string, params?: QueryValue) =>
    requestPaginated<AgentDailyTimeLog>(
      `/api/backend/support/agents/${agentId}/time-logs/`,
      { query: params },
    ),
  listAllTimeLogs: (params?: QueryValue) =>
    requestPaginated<AgentDailyTimeLog>("/api/backend/support/time-logs/", {
      query: params,
    }),
  listReassignments: (params?: QueryValue) =>
    requestPaginated<ConversationReassignment>(
      "/api/backend/support/reassignments/",
      { query: params },
    ),
  getReassignmentsSummary: (params?: QueryValue) =>
    request<ReassignmentSummaryRow[]>("/api/backend/support/reassignments/summary/", {
      query: params,
    }),

  // ----- Manual assignment actions -----
  manualAssign: (payload: ManualAssignPayload) =>
    request<AssignmentActionResponse>("/api/backend/support/queue/manual-assign/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  forceReassign: (payload: ForceReassignPayload) =>
    request<AssignmentActionResponse>("/api/backend/support/queue/force-reassign/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export type { AuthTokens };
