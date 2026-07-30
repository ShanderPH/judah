import { describe, expect, it } from "vitest";

import { MAX_JSON_BODY_BYTES, evaluateBffRoute, isBodyWithinLimit, isJsonContentType, isTrustedMutation } from "@/src/lib/api/bff-policy";

describe("versioned BFF policy", () => {
  it("allows only declared method and path combinations", () => {
    expect(evaluateBffRoute("/support/queue/status/", "GET")).toMatchObject({ ok: true });
    expect(evaluateBffRoute("/support/queue/status/", "POST")).toEqual({ ok: false, status: 405 });
    expect(evaluateBffRoute("/auth/users/", "GET")).toEqual({ ok: false, status: 404 });
    expect(evaluateBffRoute("/support//queue/status/", "GET")).toEqual({ ok: false, status: 404 });
  });

  it("requires an exact same-origin mutation context", () => {
    const trusted = new Request("https://judah.example/api/backend/support/queue/sync-novo/", {
      method: "POST",
      headers: { host: "judah.example", origin: "https://judah.example", "sec-fetch-site": "same-origin" },
    });
    const crossSite = new Request(trusted.url, {
      method: "POST",
      headers: { host: "judah.example", origin: "https://evil.example", "sec-fetch-site": "cross-site" },
    });
    expect(isTrustedMutation(trusted)).toBe(true);
    expect(isTrustedMutation(crossSite)).toBe(false);
  });

  it("accepts JSON with parameters and rejects other media types", () => {
    expect(isJsonContentType("application/json; charset=utf-8")).toBe(true);
    expect(isJsonContentType("text/plain")).toBe(false);
    expect(isJsonContentType(null)).toBe(false);
  });

  it("rejects declared and actual bodies over the policy limit", () => {
    expect(isBodyWithinLimit(MAX_JSON_BODY_BYTES + 1, "{}")).toBe(false);
    expect(isBodyWithinLimit(0, "x".repeat(MAX_JSON_BODY_BYTES + 1))).toBe(false);
    expect(isBodyWithinLimit(2, "{}")).toBe(true);
  });
});
