import type { User } from "@/src/types/api";

export const CAPABILITIES = {
  dashboardRead: "dashboard.read",
  supportAdminRead: "support.admin.read",
  agentsManage: "agents.manage",
  assignmentsManage: "assignments.manage",
  queueSync: "queue.sync",
  metricsRead: "metrics.read",
  sandboxUse: "sandbox.use",
} as const;

export type Capability = (typeof CAPABILITIES)[keyof typeof CAPABILITIES];

const routeCapabilities: ReadonlyArray<readonly [string, Capability]> = [
  ["/sandbox-chat", CAPABILITIES.sandboxUse],
  ["/auto-assignment", CAPABILITIES.supportAdminRead],
  ["/agents", CAPABILITIES.supportAdminRead],
  ["/metrics", CAPABILITIES.metricsRead],
  ["/queue", CAPABILITIES.supportAdminRead],
  ["/dashboard", CAPABILITIES.dashboardRead],
];

export function hasCapability(
  user: Pick<User, "capabilities">,
  capability: Capability,
): boolean {
  return user.capabilities.includes(capability);
}

export function requiredCapabilityForPath(pathname: string): Capability | null {
  return (
    routeCapabilities.find(
      ([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`),
    )?.[1] ?? null
  );
}

export function canAccessPath(
  user: Pick<User, "capabilities">,
  pathname: string,
): boolean {
  const required = requiredCapabilityForPath(pathname);
  return required === null || hasCapability(user, required);
}
