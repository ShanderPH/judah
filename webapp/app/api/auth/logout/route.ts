import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

import { AUTH_COOKIE_NAMES } from "@/src/lib/auth/constants";
import { backendFetch } from "@/src/lib/backend";
import { jsonWithSession } from "@/src/lib/auth/server-session";
import { markSensitiveResponse, resolveRequestId } from "@/src/lib/observability/request-context";
import { errorType, serverLogger } from "@/src/lib/observability/server-logger";

export async function POST(request: NextRequest) {
  const requestId = resolveRequestId(request.headers);
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(AUTH_COOKIE_NAMES.refreshToken)?.value ?? null;

  if (refreshToken) {
    try {
      await backendFetch("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh: refreshToken }),
      }, null, requestId);
    } catch (cause) {
      serverLogger.warn("auth.logout.backend_failure", { requestId, route: "/api/auth/logout", method: "POST", upstream: "judah", errorType: errorType(cause), outcome: "cookies_cleared" });
    }
  }

  return markSensitiveResponse(jsonWithSession({ ok: true }, { clearCookies: true }), requestId);
}
