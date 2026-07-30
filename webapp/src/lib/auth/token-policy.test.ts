import { describe, expect, it } from "vitest";

import { isExpiredToken, tokenMaxAge } from "@/src/lib/auth/token-policy";

function tokenWithExpiry(exp: number): string {
  const payload = Buffer.from(JSON.stringify({ exp })).toString("base64url");
  return `header.${payload}.signature`;
}

describe("JWT cookie expiry policy", () => {
  it("aligns max-age with the JWT exp claim", () => {
    expect(tokenMaxAge(tokenWithExpiry(1_100), 30, 1_000_000)).toBe(100);
  });

  it("distinguishes expired and malformed tokens", () => {
    expect(isExpiredToken(tokenWithExpiry(999), 1_000_000)).toBe(true);
    expect(isExpiredToken("malformed", 1_000_000)).toBe(false);
    expect(tokenMaxAge("malformed", 30, 1_000_000)).toBe(30);
  });
});
