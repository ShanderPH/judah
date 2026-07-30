import { describe, expect, it } from "vitest";

import { CAPABILITIES, canAccessPath, hasCapability } from "@/src/lib/auth/access-policy";

const viewer = { capabilities: [CAPABILITIES.dashboardRead] };
const manager = {
  capabilities: [
    CAPABILITIES.dashboardRead,
    CAPABILITIES.supportAdminRead,
    CAPABILITIES.agentsManage,
    CAPABILITIES.assignmentsManage,
    CAPABILITIES.queueSync,
    CAPABILITIES.metricsRead,
  ],
};
const admin = { capabilities: [...manager.capabilities, CAPABILITIES.sandboxUse] };

describe("capability access policy", () => {
  it("keeps viewer access limited to the dashboard", () => {
    expect(canAccessPath(viewer, "/dashboard")).toBe(true);
    expect(canAccessPath(viewer, "/agents")).toBe(false);
    expect(hasCapability(viewer, CAPABILITIES.queueSync)).toBe(false);
  });

  it("allows managers to operate support but not the sandbox", () => {
    expect(canAccessPath(manager, "/queue")).toBe(true);
    expect(canAccessPath(manager, "/metrics")).toBe(true);
    expect(canAccessPath(manager, "/sandbox-chat")).toBe(false);
  });

  it("reserves sandbox access for the explicit capability", () => {
    expect(canAccessPath(admin, "/sandbox-chat")).toBe(true);
  });
});
