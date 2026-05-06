import { judahApi } from "@/src/lib/api/client";
import { safeNumber } from "@/src/lib/utils/format";

export async function loadDashboardOverview() {
  const [
    health,
    queueStatus,
    queueHealth,
    businessHours,
    queueMetrics,
    reports,
    agents,
    agentMetricsSummary,
  ] = await Promise.all([
    judahApi.getHealth(),
    judahApi.getQueueStatus(),
    judahApi.getQueueHealth(),
    judahApi.getBusinessHours(),
    judahApi.listQueueMetrics({ days: 7, limit: 7, offset: 0 }),
    judahApi.listReports({ days: 7, limit: 7, offset: 0 }),
    judahApi.listAgents({ limit: 50, offset: 0 }),
    judahApi.getAgentMetricsSummary({ days: 7 }),
  ]);

  return {
    agents: agents.results,
    agentMetricsSummary,
    businessHours,
    health,
    latestQueueMetric: queueMetrics.results[0] ?? null,
    latestReport: reports.results[0] ?? null,
    queueHealth,
    queueMetrics: queueMetrics.results,
    queueStatus,
  };
}

export async function loadAutoAssignmentOverview() {
  const [
    queueHealth,
    queueMetrics,
    businessHours,
    specialSchedules,
    agents,
    reassignments,
  ] = await Promise.all([
    judahApi.getQueueHealth(),
    judahApi.listQueueMetrics({ days: 14, limit: 14, offset: 0 }),
    judahApi.getBusinessHours(),
    judahApi.listSpecialSchedules(),
    judahApi.listAgents({ limit: 100, offset: 0 }),
    judahApi.listReassignments({ days: 14, limit: 25, offset: 0 }),
  ]);

  return {
    agents: agents.results,
    businessHours,
    latestMetric: queueMetrics.results[0] ?? null,
    queueHealth,
    queueMetrics: queueMetrics.results,
    reassignments: reassignments.results,
    specialSchedules,
  };
}

export async function loadMetricsOverview() {
  const [
    queueMetrics,
    reports,
    queueHealth,
    agentMetrics,
    agentMetricsSummary,
    timeLogs,
    reassignmentsSummary,
  ] = await Promise.all([
    judahApi.listQueueMetrics({ days: 30, limit: 30, offset: 0 }),
    judahApi.listReports({ days: 30, limit: 30, offset: 0 }),
    judahApi.getQueueHealth(),
    judahApi.listAgentMetrics({ days: 30, limit: 100, offset: 0 }),
    judahApi.getAgentMetricsSummary({ days: 30 }),
    judahApi.listAllTimeLogs({ days: 14, limit: 100, offset: 0 }),
    judahApi.getReassignmentsSummary({ days: 30 }),
  ]);

  const latestMetric = queueMetrics.results[0] ?? null;
  const latestReport = reports.results[0] ?? null;

  return {
    agentMetrics: agentMetrics.results,
    agentMetricsSummary,
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

export async function loadAgentsAdminOverview() {
  const [agents, agentMetricsSummary, queueHealth] = await Promise.all([
    judahApi.listAgents({ limit: 100, offset: 0 }),
    judahApi.getAgentMetricsSummary({ days: 30 }),
    judahApi.getQueueHealth(),
  ]);

  return {
    agents: agents.results,
    agentMetricsSummary,
    queueHealth,
  };
}
