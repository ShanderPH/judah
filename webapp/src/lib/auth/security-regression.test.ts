import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { isCredentialRejectionStatus } from "@/src/lib/auth/upstream-status";

describe("auth transport regression", () => {
  it("never classifies upstream 5xx as invalid credentials", () => {
    expect(isCredentialRejectionStatus(401)).toBe(true);
    expect(isCredentialRejectionStatus(403)).toBe(true);
    expect(isCredentialRejectionStatus(500)).toBe(false);
    expect(isCredentialRejectionStatus(503)).toBe(false);
  });

  it("never places the refresh token in a backend URL", () => {
    const backendSource = readFileSync(new URL("../backend.ts", import.meta.url), "utf8");
    expect(backendSource).not.toContain("refresh?refresh=");
    expect(backendSource).toContain('body: JSON.stringify({ refresh: refreshToken })');
  });

  it("does not use ad hoc console logging in sensitive route handlers", () => {
    const routes = [
      "../../../app/api/auth/login/route.ts",
      "../../../app/api/auth/session/route.ts",
      "../../../app/api/backend/[...path]/route.ts",
      "../../../app/api/hubspot/visitor-token/route.ts",
    ];
    for (const route of routes) {
      const source = readFileSync(new URL(route, import.meta.url), "utf8");
      expect(source).not.toContain("console.error");
      expect(source).not.toContain("await response.text()");
    }
  });

  it("refreshes and retries a proxied 401 before clearing cookies", () => {
    const routeSource = readFileSync(
      new URL("../../../app/api/backend/[...path]/route.ts", import.meta.url),
      "utf8",
    );
    const refreshIndex = routeSource.indexOf("refreshBackendTokens(retryRefreshToken");
    const clearIndex = routeSource.indexOf("backendResponse.status === 401) clearAuthCookies");
    expect(refreshIndex).toBeGreaterThan(-1);
    expect(clearIndex).toBeGreaterThan(refreshIndex);
  });

  it("throws on auth upstream 5xx instead of returning an invalid session", () => {
    const backendSource = readFileSync(new URL("../backend.ts", import.meta.url), "utf8");
    expect(backendSource).toContain('throw new BackendHttpError("/auth/me", response.status)');
    expect(backendSource).toContain('throw new BackendHttpError("/auth/refresh", response.status)');
  });
});
