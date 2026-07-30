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
import { normalizePaginatedResponse } from "@/src/lib/api/pagination";

export { normalizePaginatedResponse } from "@/src/lib/api/pagination";

interface LoginPayload {
  identity: string;
  password: string;
}

interface QueryValue {
  [key: string]: boolean | number | string | undefined;
}

interface RequestOptions {
  signal?: AbortSignal;
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

function idempotencyHeaders(): HeadersInit {
  return { "Idempotency-Key": crypto.randomUUID() };
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

  const method = (init?.method ?? "GET").toUpperCase();
  const retryable = method === "GET";
  let response: Response | null = null;

  for (let attempt = 0; attempt < (retryable ? 2 : 1); attempt += 1) {
    try {
      response = await fetch(`${path}${buildQuery(init?.query)}`, {
        ...init,
        credentials: "same-origin",
        cache: "no-store",
        headers,
      });
    } catch (error) {
      if (init?.signal?.aborted || attempt > 0) throw error;
    }

    if (response && ![429, 502, 503, 504].includes(response.status)) break;
    if (attempt === 0) {
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(resolve, 250);
        init?.signal?.addEventListener(
          "abort",
          () => {
            window.clearTimeout(timeout);
            reject(new DOMException("Request aborted", "AbortError"));
          },
          { once: true },
        );
      });
    }
  }

  if (!response) throw new Error("Backend indisponivel.");

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) {
    throw new ApiClientError(response.status, (payload as ApiErrorPayload) ?? { detail: "Request failed." });
  }

  return payload as T;
}

async function requestPaginated<T>(
  path: string,
  init?: RequestInit & {
    query?: QueryValue;
  },
): Promise<PaginatedResponse<T>> {
  const raw = await request<unknown>(path, init);
  return normalizePaginatedResponse<T>(raw, { path, query: init?.query });
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
  getHealth: (options?: RequestOptions) => request<HealthResponse>("/api/backend/health", options),
  getQueueStatus: (options?: RequestOptions) => request<QueueStatusResponse>("/api/backend/support/queue/status", options),
  getQueueHealth: (options?: RequestOptions) => request<QueueHealthResponse>("/api/backend/support/queue/health", options),
  getBusinessHours: (options?: RequestOptions) => request<BusinessHoursResponse>("/api/backend/support/business-hours", options),
  listSpecialSchedules: (options?: RequestOptions) => request<SpecialSchedule[]>("/api/backend/support/special-schedules", options),
  syncNovo: () =>
    request<SyncNovoResponse>("/api/backend/support/queue/sync-novo", {
      method: "POST",
      headers: idempotencyHeaders(),
    }),
  listPendingConversations: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<PendingConversation>("/api/backend/support/queue/pending", {
      query: params,
      ...options,
    }),
  listAssignedConversations: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<AssignedConversation>("/api/backend/support/queue/assigned", {
      query: params,
      ...options,
    }),
  listQueueMetrics: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<QueueMetric>("/api/backend/support/queue/metrics", {
      query: params,
      ...options,
    }),
  listReports: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<DailyReport>("/api/backend/analytics/reports", {
      query: params,
      ...options,
    }),

  // ----- Agents administration -----
  listAgents: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<Agent>("/api/backend/support/agents", { query: params, ...options }),
  retrieveAgent: (agentId: string) =>
    request<Agent>(`/api/backend/support/agents/${agentId}`),
  createAgent: (payload: CreateAgentPayload) =>
    request<Agent>("/api/backend/support/agents", {
      method: "POST",
      headers: idempotencyHeaders(),
      body: JSON.stringify(payload),
    }),
  updateAgent: (agentId: string, payload: UpdateAgentPayload) =>
    request<Agent>(`/api/backend/support/agents/${agentId}`, {
      method: "PATCH",
      headers: idempotencyHeaders(),
      body: JSON.stringify(payload),
    }),
  inactivateAgent: (agentId: string) =>
    request<Agent>(`/api/backend/support/agents/${agentId}/inactivate`, {
      method: "POST",
      headers: idempotencyHeaders(),
    }),
  reactivateAgent: (agentId: string) =>
    request<Agent>(`/api/backend/support/agents/${agentId}/reactivate`, {
      method: "POST",
      headers: idempotencyHeaders(),
    }),

  // ----- Aggregated reads -----
  listAgentMetrics: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<AgentMetricsRow>("/api/backend/support/metrics/agents", {
      query: params,
      ...options,
    }),
  getAgentMetricsSummary: (params?: QueryValue, options?: RequestOptions) =>
    request<AgentMetricsSummary>("/api/backend/support/metrics/agents/summary", {
      query: params,
      ...options,
    }),
  listAgentMetricsForAgent: (agentId: string, params?: QueryValue) =>
    requestPaginated<AgentMetricsRow>(
      `/api/backend/support/agents/${agentId}/metrics`,
      { query: params },
    ),
  listAgentTimeLogs: (agentId: string, params?: QueryValue) =>
    requestPaginated<AgentDailyTimeLog>(
      `/api/backend/support/agents/${agentId}/time-logs`,
      { query: params },
    ),
  listAllTimeLogs: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<AgentDailyTimeLog>("/api/backend/support/time-logs", {
      query: params,
      ...options,
    }),
  listReassignments: (params?: QueryValue, options?: RequestOptions) =>
    requestPaginated<ConversationReassignment>(
      "/api/backend/support/reassignments",
      { query: params, ...options },
    ),
  getReassignmentsSummary: (params?: QueryValue, options?: RequestOptions) =>
    request<ReassignmentSummaryRow[]>("/api/backend/support/reassignments/summary", {
      query: params,
      ...options,
    }),

  // ----- Manual assignment actions -----
  manualAssign: (payload: ManualAssignPayload) =>
    request<AssignmentActionResponse>("/api/backend/support/queue/manual-assign", {
      method: "POST",
      headers: idempotencyHeaders(),
      body: JSON.stringify(payload),
    }),
  forceReassign: (payload: ForceReassignPayload) =>
    request<AssignmentActionResponse>("/api/backend/support/queue/force-reassign", {
      method: "POST",
      headers: idempotencyHeaders(),
      body: JSON.stringify(payload),
    }),
};

export type { AuthTokens };
