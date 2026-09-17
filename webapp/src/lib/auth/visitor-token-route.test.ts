import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/hubspot/visitor-token/route";

const mocks = vi.hoisted(() => ({ session: vi.fn(), fetch: vi.fn(), log: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({}) }));
vi.mock("@/src/lib/auth/server-session", () => ({
  readAuthTokens: () => ({}), resolveSessionFromTokens: mocks.session,
}));
vi.mock("@/src/lib/observability/server-logger", () => ({
  serverLogger: { error: mocks.log }, errorType: () => "SyntheticError",
}));

function authenticate(role: string, capabilities = role === "admin" ? ["sandbox.use"] : []) {
  mocks.session.mockResolvedValue({ status: "authenticated", tokens: null, user: {
    id: 1, email: "security@example.invalid", first_name: "Test", last_name: "User", role, capabilities,
  } });
}

const request = () => new NextRequest("http://localhost/api/hubspot/visitor-token", { method: "POST" });

describe("visitor token authorization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", mocks.fetch);
    vi.stubEnv("HUBSPOT_SANDBOX_ACCESS_TOKEN", "synthetic-server-secret");
    vi.stubEnv("HUBSPOT_SANDBOX_OAUTH_ACCESS_TOKEN", "");
    mocks.fetch.mockResolvedValue(Response.json({ token: "synthetic-visitor-token" }));
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it.each(["viewer", "agent", "manager"])("denies %s before provider access", async (role) => {
    authenticate(role);
    const response = await POST(request());
    expect(response.status).toBe(403);
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(await response.text()).not.toContain("synthetic-server-secret");
    expect(response.headers.get("cache-control")).toContain("no-store");
  });

  it.each(["viewer", "agent", "manager"])("denies %s even when provider is unconfigured", async (role) => {
    authenticate(role);
    vi.stubEnv("HUBSPOT_SANDBOX_ACCESS_TOKEN", "");
    expect((await POST(request())).status).toBe(403);
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(mocks.log).not.toHaveBeenCalled();
  });

  it.each(["synthetic-server-secret", ""])("requires session regardless of provider configuration", async (secret) => {
    vi.stubEnv("HUBSPOT_SANDBOX_ACCESS_TOKEN", secret);
    mocks.session.mockResolvedValue({ status: "missing", user: null, tokens: null });
    expect((await POST(request())).status).toBe(401);
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it("allows admin using the existing provider contract", async () => {
    authenticate("admin");
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ token: "synthetic-visitor-token" });
    expect(mocks.fetch).toHaveBeenCalledExactlyOnceWith(
      "https://api.hubapi.com/visitor-identification/v3/tokens/create",
      expect.objectContaining({ method: "POST", cache: "no-store", body: JSON.stringify({
        email: "security@example.invalid", firstName: "Test", lastName: "User",
        hsCustomerAgentContext: { judahUserId: "1", source: "judah-sandbox-chat" },
      }) }),
    );
    expect(JSON.stringify(mocks.log.mock.calls)).not.toContain("synthetic-server-secret");
  });

  it("checks capability even for an admin", async () => {
    authenticate("admin", []);
    expect((await POST(request())).status).toBe(403);
    expect(mocks.fetch).not.toHaveBeenCalled();
  });
});
