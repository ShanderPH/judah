import { describe, expect, it } from "vitest";

import { attachRequestId, markSensitiveResponse, resolveRequestId } from "@/src/lib/observability/request-context";

describe("request correlation", () => {
  it("preserves a valid request ID and replaces unsafe input", () => {
    expect(resolveRequestId(new Headers({ "x-request-id": "request-123" }))).toBe("request-123");
    expect(resolveRequestId(new Headers({ "x-request-id": "Bearer secret" }))).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("marks sensitive responses as no-store and correlated", () => {
    const response = markSensitiveResponse(new Response(), "request-123");
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("x-request-id")).toBe("request-123");
    expect(attachRequestId(new Response(), "request-456").headers.get("x-request-id")).toBe("request-456");
  });
});
