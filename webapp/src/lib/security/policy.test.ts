import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { buildContentSecurityPolicy, THEME_BOOTSTRAP } from "@/src/lib/security/policy";

describe("security policy", () => {
  const themeHash = createHash("sha256").update(THEME_BOOTSTRAP).digest("base64");

  it("allows the inline theme bootstrap by hash and denies risky defaults", () => {
    const policy = buildContentSecurityPolicy(themeHash);
    expect(policy).toContain(`script-src 'self' 'sha256-${themeHash}'`);
    expect(policy).toContain("object-src 'none'");
    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).not.toContain("hs-scripts.com");
  });

  it("limits HubSpot origins to the sandbox policy", () => {
    const policy = buildContentSecurityPolicy(themeHash, true);
    expect(policy).toContain("https://js-na1.hs-scripts.com");
    expect(policy).toContain("frame-src https://*.hubspot.com");
  });
});
