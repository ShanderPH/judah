import { createHash } from "node:crypto";
import type { NextConfig } from "next";

import { buildContentSecurityPolicy, THEME_BOOTSTRAP } from "./src/lib/security/policy";

const themeHash = createHash("sha256").update(THEME_BOOTSTRAP).digest("base64");
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
  },
];
const noStore = {
  key: "Cache-Control",
  value: "private, no-cache, no-store, max-age=0, must-revalidate",
};

const nextConfig: NextConfig = {
  poweredByHeader: false,
  turbopack: {
    root: process.cwd(),
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          ...securityHeaders,
          {
            key: "Content-Security-Policy-Report-Only",
            value: buildContentSecurityPolicy(themeHash),
          },
        ],
      },
      {
        source: "/sandbox-chat",
        headers: [
          {
            key: "Content-Security-Policy-Report-Only",
            value: buildContentSecurityPolicy(themeHash, true),
          },
          noStore,
        ],
      },
      { source: "/api/auth/:path*", headers: [noStore] },
      { source: "/api/backend/:path*", headers: [noStore] },
      { source: "/api/hubspot/:path*", headers: [noStore] },
      { source: "/dashboard/:path*", headers: [noStore] },
      { source: "/queue/:path*", headers: [noStore] },
      { source: "/auto-assignment/:path*", headers: [noStore] },
      { source: "/agents/:path*", headers: [noStore] },
      { source: "/metrics/:path*", headers: [noStore] },
    ];
  },
};

export default nextConfig;
