import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

import {
  BackendConfigurationError,
  BackendHttpError,
  BackendUnreachableError,
} from "@/src/lib/backend";
import { jsonWithSession, readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";
import { markSensitiveResponse, resolveRequestId } from "@/src/lib/observability/request-context";
import { errorType, serverLogger } from "@/src/lib/observability/server-logger";
import type { ApiErrorPayload } from "@/src/types/api";

export async function GET(request: NextRequest) {
  const requestId = resolveRequestId(request.headers);
  const cookieStore = await cookies();

  try {
    const session = await resolveSessionFromTokens(readAuthTokens(cookieStore), requestId);

    if (session.status !== "authenticated") {
      return markSensitiveResponse(jsonWithSession(
        { detail: session.status === "missing" ? "Sessao ausente." : "Sessao expirada ou invalida." } satisfies ApiErrorPayload,
        { clearCookies: true, status: 401 },
      ), requestId);
    }

    return markSensitiveResponse(jsonWithSession({ user: session.user }, { tokens: session.tokens }), requestId);
  } catch (cause) {
    if (cause instanceof BackendHttpError) {
      const status = cause.status >= 500 ? 502 : cause.status;
      serverLogger.error("auth.session.backend_failure", { requestId, route: "/api/auth/session", method: "GET", upstream: "judah", errorType: errorType(cause), status });
      return markSensitiveResponse(jsonWithSession(
        { detail: "Backend Judah indisponivel para validar a sessao." } satisfies ApiErrorPayload,
        { status },
      ), requestId);
    }
    if (cause instanceof BackendConfigurationError) {
      serverLogger.error("auth.session.backend_misconfigured", { requestId, route: "/api/auth/session", method: "GET", upstream: "judah", errorType: errorType(cause), status: 503 });
      return markSensitiveResponse(jsonWithSession(
        { detail: "Configuracao do servidor incompleta. Contate o administrador." } satisfies ApiErrorPayload,
        { status: 503 },
      ), requestId);
    }
    if (cause instanceof BackendUnreachableError) {
      serverLogger.error("auth.session.backend_unreachable", { requestId, route: "/api/auth/session", method: "GET", upstream: "judah", errorType: errorType(cause), status: 502 });
      return markSensitiveResponse(jsonWithSession(
        { detail: "Backend Judah indisponivel no momento." } satisfies ApiErrorPayload,
        { status: 502 },
      ), requestId);
    }
    serverLogger.error("auth.session.unexpected_failure", { requestId, route: "/api/auth/session", method: "GET", errorType: errorType(cause), status: 500 });
    return markSensitiveResponse(jsonWithSession(
      { detail: "Erro interno ao validar a sessao." } satisfies ApiErrorPayload,
      { status: 500 },
    ), requestId);
  }
}
