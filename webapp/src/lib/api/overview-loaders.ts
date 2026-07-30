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
import { safeNumber } from "@/src/lib/utils/format";

interface QueryValue {
  [key: string]: boolean | number | string | undefined;
}

export interface OverviewReader {
  getHealth(): Promise<HealthResponse>;
  getQueueStatus(): Promise<QueueStatusResponse>;
  getQueueHealth(): Promise<QueueHealthResponse>;
  getBusinessHours(): Promise<BusinessHoursResponse>;
  listSpecialSchedules(): Promise<SpecialSchedule[]>;
  listQueueMetrics(params?: QueryValue): Promise<PaginatedResponse<QueueMetric>>;
  listReports(params?: QueryValue): Promise<PaginatedResponse<DailyReport>>;
  listAgents(params?: QueryValue): Promise<PaginatedResponse<Agent>>;
  getAgentMetricsSummary(params?: QueryValue): Promise<AgentMetricsSummary>;
  listReassignments(params?: QueryValue): Promise<PaginatedResponse<ConversationReassignment>>;
  listAgentMetrics(params?: QueryValue): Promise<PaginatedResponse<AgentMetricsRow>>;
  listAllTimeLogs(params?: QueryValue): Promise<PaginatedResponse<AgentDailyTimeLog>>;
  getReassignmentsSummary(params?: QueryValue): Promise<ReassignmentSummaryRow[]>;
}

const emptyPage = <T>(): PaginatedResponse<T> => ({
  count: 0,
  next: null,
  previous: null,
  results: [],
});

const emptyQueueHealth: QueueHealthResponse = {
  timestamp: "",
  summary: {
    total_agents: 0,
    online_agents: 0,
    away_agents: 0,
    eligible_agents: 0,
    pending_queue_depth: 0,
    system_ok: false,
    warnings: [],
    issues: [],
  },
  absent_agents: [],
  eligible_agents: [],
  pending_tickets: [],
  last_assignments: [],
};

const emptyBusinessHours: BusinessHoursResponse = {
  name: "Indisponivel",
  is_active: false,
  monday: "",
  tuesday: "",
  wednesday: "",
  thursday: "",
  friday: "",
  saturday: "",
  sunday: "",
  timezone_name: "America/Sao_Paulo",
  is_currently_business_hours: false,
};

const emptyAgentSummary: AgentMetricsSummary = {
  period_days: 0,
  total_agents_with_data: 0,
  total_chats: 0,
  total_chats_closed: 0,
  avg_handle_time_min: 0,
  avg_first_response_min: 0,
  avg_resolution_rate: 0,
  avg_csat: 0,
};

async function settle<T>(
  label: string,
  promise: Promise<T>,
  fallback: T,
  degradedServices: string[],
): Promise<T> {
  try {
    return await promise;
  } catch {
    degradedServices.push(label);
    return fallback;
  }
}

export async function readDashboardOverview(api: OverviewReader) {
  const degradedServices: string[] = [];
  const [health, queueStatus, queueHealth, businessHours, queueMetrics, reports, agents, agentMetricsSummary] =
    await Promise.all([
      settle("health", api.getHealth(), { status: "degraded", timestamp: "", version: "", checks: {} }, degradedServices),
      settle("queue-status", api.getQueueStatus(), { online_agents: 0, eligible_agents: 0, pending_queue_depth: 0, agents: [] }, degradedServices),
      settle("queue-health", api.getQueueHealth(), emptyQueueHealth, degradedServices),
      settle("business-hours", api.getBusinessHours(), emptyBusinessHours, degradedServices),
      settle("queue-metrics", api.listQueueMetrics({ days: 7, limit: 7, offset: 0 }), emptyPage<QueueMetric>(), degradedServices),
      settle("analytics-reports", api.listReports({ days: 7, limit: 7, offset: 0 }), emptyPage<DailyReport>(), degradedServices),
      settle("agents", api.listAgents({ limit: 50, offset: 0 }), emptyPage<Agent>(), degradedServices),
      settle("agent-metrics", api.getAgentMetricsSummary({ days: 7 }), emptyAgentSummary, degradedServices),
    ]);

  return {
    agents: agents.results,
    agentMetricsSummary,
    businessHours,
    degradedServices,
    health,
    latestQueueMetric: queueMetrics.results[0] ?? null,
    latestReport: reports.results[0] ?? null,
    queueHealth,
    queueMetrics: queueMetrics.results,
    queueStatus,
  };
}

export async function readAutoAssignmentOverview(api: OverviewReader) {
  const degradedServices: string[] = [];
  const [queueHealth, queueMetrics, businessHours, specialSchedules, agents, reassignments] = await Promise.all([
    settle("queue-health", api.getQueueHealth(), emptyQueueHealth, degradedServices),
    settle("queue-metrics", api.listQueueMetrics({ days: 14, limit: 14, offset: 0 }), emptyPage<QueueMetric>(), degradedServices),
    settle("business-hours", api.getBusinessHours(), emptyBusinessHours, degradedServices),
    settle("special-schedules", api.listSpecialSchedules(), [], degradedServices),
    settle("agents", api.listAgents({ limit: 100, offset: 0 }), emptyPage<Agent>(), degradedServices),
    settle("reassignments", api.listReassignments({ days: 14, limit: 25, offset: 0 }), emptyPage<ConversationReassignment>(), degradedServices),
  ]);
  return {
    agents: agents.results,
    businessHours,
    degradedServices,
    latestMetric: queueMetrics.results[0] ?? null,
    queueHealth,
    queueMetrics: queueMetrics.results,
    reassignments: reassignments.results,
    specialSchedules,
  };
}

export async function readMetricsOverview(api: OverviewReader) {
  const degradedServices: string[] = [];
  const [queueMetrics, reports, queueHealth, agentMetrics, agentMetricsSummary, timeLogs, reassignmentsSummary] = await Promise.all([
    settle("queue-metrics", api.listQueueMetrics({ days: 30, limit: 30, offset: 0 }), emptyPage<QueueMetric>(), degradedServices),
    settle("analytics-reports", api.listReports({ days: 30, limit: 30, offset: 0 }), emptyPage<DailyReport>(), degradedServices),
    settle("queue-health", api.getQueueHealth(), emptyQueueHealth, degradedServices),
    settle("agent-metrics", api.listAgentMetrics({ days: 30, limit: 100, offset: 0 }), emptyPage<AgentMetricsRow>(), degradedServices),
    settle("agent-summary", api.getAgentMetricsSummary({ days: 30 }), emptyAgentSummary, degradedServices),
    settle("time-logs", api.listAllTimeLogs({ days: 14, limit: 100, offset: 0 }), emptyPage<AgentDailyTimeLog>(), degradedServices),
    settle("reassignments", api.getReassignmentsSummary({ days: 30 }), [], degradedServices),
  ]);
  const latestMetric = queueMetrics.results[0] ?? null;
  const latestReport = reports.results[0] ?? null;
  return {
    agentMetrics: agentMetrics.results,
    agentMetricsSummary,
    degradedServices,
    latestMetric,
    latestReport,
    queueHealth,
    queueMetrics: queueMetrics.results,
    reassignmentsSummary,
    reports: reports.results,
    timeLogs: timeLogs.results,
    summary: {
      avgHandleMinutes: safeNumber(latestMetric?.avg_handle_time_minutes),
      avgWaitSeconds: safeNumber(latestMetric?.avg_queue_wait_seconds),
      totalAssigned: latestMetric?.total_assigned ?? 0,
      totalClosed: latestMetric?.total_closed ?? 0,
    },
  };
}

export async function readAgentsAdminOverview(api: OverviewReader) {
  const degradedServices: string[] = [];
  const [agents, agentMetricsSummary, queueHealth] = await Promise.all([
    settle("agents", api.listAgents({ limit: 100, offset: 0 }), emptyPage<Agent>(), degradedServices),
    settle("agent-metrics", api.getAgentMetricsSummary({ days: 30 }), emptyAgentSummary, degradedServices),
    settle("queue-health", api.getQueueHealth(), emptyQueueHealth, degradedServices),
  ]);
  return { agents: agents.results, agentMetricsSummary, degradedServices, queueHealth };
}

export type DashboardOverviewData = Awaited<ReturnType<typeof readDashboardOverview>>;
export type AutoAssignmentOverviewData = Awaited<ReturnType<typeof readAutoAssignmentOverview>>;
export type MetricsOverviewData = Awaited<ReturnType<typeof readMetricsOverview>>;
export type AgentsAdminOverviewData = Awaited<ReturnType<typeof readAgentsAdminOverview>>;
