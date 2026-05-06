export type Role = "admin" | "manager" | "agent" | "viewer";

export interface ApiErrorPayload {
  detail: string;
  errors?: Record<string, unknown>;
  service?: string;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface AuthTokens {
  access: string;
  refresh: string;
}

export interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  role: Role;
  avatar_url: string;
  is_ai_agent: boolean;
}

export interface SessionPayload {
  user: User;
}

export interface HealthResponse {
  status: "healthy" | "degraded";
  timestamp: string;
  version: string;
  checks: Record<string, string>;
}

export interface QueueAgentSnapshot {
  id: string;
  name: string;
  hubspot_owner_id: number;
  status: string;
  current_chats: number;
  max_chats: number;
  last_assignment_at: string | null;
}

export interface QueueStatusResponse {
  online_agents: number;
  eligible_agents: number;
  pending_queue_depth: number;
  agents: QueueAgentSnapshot[];
}

export interface PendingConversation {
  id: string;
  hubspot_ticket_id: string;
  pipeline_id: string;
  contact_name: string | null;
  contact_email: string | null;
  priority: string | null;
  subject: string | null;
  entered_queue_at: string;
  created_at: string;
}

export interface AssignedConversation {
  id: string;
  hubspot_ticket_id: string;
  agent_name: string;
  hubspot_owner_id: number;
  pipeline_id: string;
  entered_queue_at: string | null;
  assigned_at: string;
  queue_wait_seconds: string | null;
  closed_at: string | null;
  closed_by_agent_name: string | null;
  total_handle_time_minutes: string | null;
  contact_name: string | null;
  priority: string | null;
  subject: string | null;
}

export interface QueueMetric {
  id: string;
  metric_date: string;
  total_entered_queue: number;
  total_assigned: number;
  total_closed: number;
  avg_queue_wait_seconds: string | null;
  min_queue_wait_seconds: string | null;
  max_queue_wait_seconds: string | null;
  p50_queue_wait_seconds: string | null;
  p95_queue_wait_seconds: string | null;
  avg_handle_time_minutes: string | null;
  assignments_by_agent: Record<string, number>;
}

export interface QueueSummary {
  total_agents: number;
  online_agents: number;
  away_agents: number;
  eligible_agents: number;
  pending_queue_depth: number;
  system_ok: boolean;
  warnings: string[];
  issues: string[];
}

export interface DiagnosticAgent {
  id: string;
  name: string;
  email: string;
  hubspot_owner_id: number;
  status: string;
  current_chats: number;
  max_chats: number;
  eligible: boolean;
  at_capacity: boolean;
  auto_assign_enabled: boolean | null;
  last_assignment_at: string | null;
  is_last_assigned: boolean;
}

export interface AbsentAgent {
  name: string;
  hubspot_owner_id: number;
  status: string;
  open_chats: number;
}

export interface PendingTicketDiagnostic {
  hubspot_ticket_id: string;
  priority: string | null;
  contact_name: string | null;
  entered_queue_at: string;
  wait_seconds: number;
  queue_position?: number;
  queue_status?: string;
  assignment_attempts?: number;
}

export interface LastAssignment {
  ticket_id: string;
  agent_name: string;
  hubspot_owner_id: number | null;
  assignment_type: string;
  queue_wait_seconds: number | null;
  assigned_at: string;
}

export interface QueueHealthResponse {
  timestamp: string;
  summary: QueueSummary;
  absent_agents: AbsentAgent[];
  eligible_agents: DiagnosticAgent[];
  pending_tickets: PendingTicketDiagnostic[];
  last_assignments: LastAssignment[];
}

export interface BusinessHoursResponse {
  name: string;
  is_active: boolean;
  monday: string;
  tuesday: string;
  wednesday: string;
  thursday: string;
  friday: string;
  saturday: string;
  sunday: string;
  timezone_name: string;
  is_currently_business_hours: boolean;
}

export interface SpecialSchedule {
  id: string;
  date: string;
  schedule_type: string;
  start_hour: number | null;
  end_hour: number | null;
  reason: string;
}

export interface SyncNovoResponse {
  created: number;
  skipped: number;
  already_assigned: number;
  total_from_hubspot: number;
  queued_for_assignment: boolean;
  error: string | null;
}

export interface DailyReport {
  date: string;
  total_tickets_opened: number;
  total_tickets_resolved: number;
  total_tickets_escalated: number;
  avg_resolution_hours: number;
  avg_first_response_hours: number;
  sla_compliance_rate: number;
  ai_handled_count: number;
  ai_deflection_rate: number;
}

export type AgentStatus = "online" | "away" | "offline" | "busy";

export interface Agent {
  id: string;
  name: string;
  agent_email: string;
  hubspot_owner_id: number;
  team: string | null;
  manager_email: string | null;
  status_enum: AgentStatus;
  current_simultaneous_chats: number;
  max_simultaneous_chats: number;
  auto_assign_enabled: boolean;
  is_active: boolean | null;
  timezone: string;
  last_assignment_at: string | null;
  total_assignments: number;
  online_time_seconds_today: number;
  away_time_seconds_today: number;
  last_status_change_at: string | null;
}

export interface CreateAgentPayload {
  name: string;
  agent_email: string;
  hubspot_owner_id: number;
  team?: string | null;
  manager_email?: string | null;
  timezone?: string;
  max_simultaneous_chats?: number;
  auto_assign_enabled?: boolean;
}

export interface UpdateAgentPayload {
  name?: string;
  team?: string | null;
  manager_email?: string | null;
  timezone?: string;
  max_simultaneous_chats?: number;
  auto_assign_enabled?: boolean;
  is_active?: boolean;
  status_enum?: AgentStatus;
}

export interface AgentMetricsRow {
  id: string;
  agent_id: number;
  period_start: string | null;
  period_end: string | null;
  average_online_time: number;
  average_away_time: number;
  average_daily_tickets: number;
  average_response_time_min: number;
  average_ticket_time_min: number;
  tickets_transfer: number;
  csat: number;
  total_chats: number;
  chats_closed: number;
  first_response_time_avg_min: string | null;
  resolution_rate: string | null;
  customer_satisfaction_avg: string | null;
  last_time_updated: string;
}

export interface AgentMetricsSummary {
  period_days: number;
  total_agents_with_data: number;
  total_chats: number;
  total_chats_closed: number;
  avg_handle_time_min: number;
  avg_first_response_min: number;
  avg_resolution_rate: number;
  avg_csat: number;
}

export interface AgentDailyTimeLog {
  id: string;
  agent_id: string;
  log_date: string;
  online_time_seconds: number;
  away_time_seconds: number;
  status_transitions: number;
}

export interface ConversationReassignment {
  id: string;
  hubspot_ticket_id: string;
  from_agent_name: string | null;
  from_hubspot_owner_id: number | null;
  to_agent_name: string | null;
  to_hubspot_owner_id: number | null;
  reassigned_at: string;
  time_with_previous_agent_seconds: string | null;
  reassignment_source: string;
}

export interface ReassignmentSummaryRow {
  hubspot_owner_id: number;
  agent_name: string | null;
  transferred_in: number;
  transferred_out: number;
  net: number;
}

export interface AssignmentActionResponse {
  success: boolean;
  hubspot_ticket_id: string;
  agent_id: string | null;
  agent_name: string | null;
  detail: string;
}

export interface ManualAssignPayload {
  hubspot_ticket_id: string;
  agent_id: string;
}

export interface ForceReassignPayload {
  hubspot_ticket_id: string;
  target_agent_id: string;
  reason?: string;
}
