import { CAPABILITIES, type Capability } from "@/src/lib/auth/access-policy";

export const BFF_POLICY_VERSION = "2026-07-29";
export const MAX_JSON_BODY_BYTES = 16 * 1024;

interface RoutePolicy {
  capability: Capability;
  methods: readonly string[];
  pattern: RegExp;
  requiresJson?: boolean;
}

const UUID = "[0-9a-fA-F-]{36}";

const policies: readonly RoutePolicy[] = [
  { pattern: /^\/health\/$/, methods: ["GET"], capability: CAPABILITIES.dashboardRead },
  { pattern: /^\/support\/queue\/(?:status|health|pending|assigned|metrics)\/$/, methods: ["GET"], capability: CAPABILITIES.supportAdminRead },
  { pattern: /^\/support\/(?:business-hours|special-schedules)\/$/, methods: ["GET"], capability: CAPABILITIES.supportAdminRead },
  { pattern: /^\/analytics\/reports\/$/, methods: ["GET"], capability: CAPABILITIES.metricsRead },
  { pattern: /^\/support\/agents\/$/, methods: ["GET"], capability: CAPABILITIES.supportAdminRead },
  { pattern: new RegExp(`^/support/agents/${UUID}/$`), methods: ["GET"], capability: CAPABILITIES.supportAdminRead },
  { pattern: /^\/support\/(?:metrics\/agents|time-logs|reassignments)\/$/, methods: ["GET"], capability: CAPABILITIES.metricsRead },
  { pattern: /^\/support\/(?:metrics\/agents|reassignments)\/summary\/$/, methods: ["GET"], capability: CAPABILITIES.metricsRead },
  { pattern: new RegExp(`^/support/agents/${UUID}/(?:metrics|time-logs)/$`), methods: ["GET"], capability: CAPABILITIES.metricsRead },
  { pattern: /^\/support\/queue\/sync-novo\/$/, methods: ["POST"], capability: CAPABILITIES.queueSync },
  { pattern: /^\/support\/agents\/$/, methods: ["POST"], capability: CAPABILITIES.agentsManage, requiresJson: true },
  { pattern: new RegExp(`^/support/agents/${UUID}/$`), methods: ["PATCH"], capability: CAPABILITIES.agentsManage, requiresJson: true },
  { pattern: new RegExp(`^/support/agents/${UUID}/(?:inactivate|reactivate)/$`), methods: ["POST"], capability: CAPABILITIES.agentsManage },
  { pattern: /^\/support\/queue\/(?:manual-assign|force-reassign)\/$/, methods: ["POST"], capability: CAPABILITIES.assignmentsManage, requiresJson: true },
];

export type PolicyDecision =
  | { ok: true; capability: Capability; requiresJson: boolean }
  | { ok: false; status: 404 | 405 };

export function evaluateBffRoute(pathname: string, method: string): PolicyDecision {
  if (!/^\/[A-Za-z0-9_/-]+\/$/.test(pathname) || pathname.includes("//")) {
    return { ok: false, status: 404 };
  }
  const pathPolicies = policies.filter((policy) => policy.pattern.test(pathname));
  if (pathPolicies.length === 0) return { ok: false, status: 404 };
  const policy = pathPolicies.find((candidate) => candidate.methods.includes(method));
  if (!policy) return { ok: false, status: 405 };
  return { ok: true, capability: policy.capability, requiresJson: policy.requiresJson ?? false };
}

export function isTrustedMutation(request: Request): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return true;
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  const fetchSite = request.headers.get("sec-fetch-site");
  if (!origin || !host || fetchSite !== "same-origin") return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export function isJsonContentType(contentType: string | null): boolean {
  return contentType?.split(";", 1)[0].trim().toLowerCase() === "application/json";
}

export function isBodyWithinLimit(declaredLength: number, body: string): boolean {
  return declaredLength <= MAX_JSON_BODY_BYTES && new TextEncoder().encode(body).byteLength <= MAX_JSON_BODY_BYTES;
}
