import { cookies } from "next/headers";

import { AUTH_COOKIE_NAMES } from "@/src/lib/auth/constants";
import { backendFetch } from "@/src/lib/backend";
import { jsonWithSession } from "@/src/lib/auth/server-session";

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(AUTH_COOKIE_NAMES.refreshToken)?.value ?? null;

  if (refreshToken) {
    try {
      await backendFetch("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh: refreshToken }),
      });
    } catch {
      // Best-effort. Even if the backend is unreachable we still clear cookies.
    }
  }

  return jsonWithSession({ ok: true }, { clearCookies: true });
}
