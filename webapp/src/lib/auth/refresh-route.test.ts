import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/auth/refresh/route";

const mocks = vi.hoisted(() => ({ session: vi.fn(), write: vi.fn(), clear: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({}) }));
vi.mock("@/src/lib/auth/server-session", () => ({
  readAuthTokens: () => ({}), resolveSessionFromTokens: mocks.session,
  writeAuthCookies: mocks.write, clearAuthCookies: mocks.clear,
}));

const base = "http://localhost:3100";
function request(next: string | null) {
  const url = new URL("/auth/refresh", base);
  if (next !== null) url.searchParams.set("next", next);
  return new NextRequest(url);
}

describe("refresh redirect boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.session.mockResolvedValue({ status: "authenticated", user: {}, tokens: { access: "synthetic-access", refresh: "synthetic-refresh" } });
  });

  it.each(["/dashboard", "/metrics?days=7#chart", "/dashboard?q=hello%20world", "/metrics?q=100%25", "/metrics?q=%25ZZ", "/reports/100%25#100%25", "/metrics?q=%C3%A7"])("preserves internal target %s and cookies", async (next) => {
    const response = await GET(request(next));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(base + next);
    expect(mocks.write).toHaveBeenCalledExactlyOnceWith(response.cookies, { access: "synthetic-access", refresh: "synthetic-refresh" });
    expect(mocks.clear).not.toHaveBeenCalled();
  });

  it.each([
    null, "", "invalid", "//127.0.0.1:3101/escape", "/\\127.0.0.1:3101/escape",
    "/%5C127.0.0.1:3101/escape", "/%5c127.0.0.1:3101/escape", "/%255c127.0.0.1:3101/escape",
    "%2f%2f127.0.0.1:3101/escape", "/%2f127.0.0.1:3101/escape", "/%252f127.0.0.1:3101/escape",
    "https://example.invalid", "javascript:alert(1)", "/\t/127.0.0.1:3101/escape",
    "/dashboard\n", "/dashboard%0a", "/dashboard%00", "/%ZZ", "/%E0%A4%A",
    "/path/..//127.0.0.1:3101/escape",
  ])("falls back safely for %s", async (next) => {
    const response = await GET(request(next));
    const location = new URL(response.headers.get("location")!);
    expect(location.origin).toBe(base);
    expect(location.href).toBe(base + "/dashboard");
  });

  it("clears cookies and sends missing sessions to login", async () => {
    mocks.session.mockResolvedValue({ status: "missing", user: null, tokens: null });
    const response = await GET(request("/\\127.0.0.1:3101/escape"));
    expect(response.headers.get("location")).toBe(base + "/login");
    expect(mocks.clear).toHaveBeenCalledExactlyOnceWith(response.cookies);
    expect(mocks.write).not.toHaveBeenCalled();
  });
});
