import { describe, expect, it } from "vitest";

import { redactLogValue, sanitizeLogFields } from "@/src/lib/observability/log-policy";

describe("server log policy", () => {
  it("redacts credentials and JWT-shaped values", () => {
    expect(redactLogValue("Authorization: Bearer secret-value")).not.toContain("secret-value");
    expect(redactLogValue("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature")).toBe("[REDACTED]");
  });

  it("keeps only the typed, non-payload event fields", () => {
    expect(sanitizeLogFields({ requestId: "request-123", upstream: "judah", status: 502 })).toEqual({
      requestId: "request-123",
      upstream: "judah",
      status: 502,
    });
  });
});
