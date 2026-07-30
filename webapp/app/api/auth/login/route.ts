import { NextResponse, type NextRequest } from "next/server";

import {
  BackendConfigurationError,
  BackendUnreachableError,
  backendFetch,
  parseJsonResponse,
} from "@/src/lib/backend";
import { jsonWithSession } from "@/src/lib/auth/server-session";
import { markSensitiveResponse, resolveRequestId } from "@/src/lib/observability/request-context";
import { errorType, serverLogger } from "@/src/lib/observability/server-logger";
import type { ApiErrorPayload, AuthTokens, User } from "@/src/types/api";

interface LoginRequestPayload {
  identity?: string;
  password?: string;
}

export async function POST(request: NextRequest) {
  const requestId = resolveRequestId(request.headers);
  const json = (payload: ApiErrorPayload, status: number) =>
    markSensitiveResponse(NextResponse.json(payload, { status }), requestId);
  let payload: LoginRequestPayload;
  try {
    payload = (await request.json()) as LoginRequestPayload;
  } catch {
    return markSensitiveResponse(NextResponse.json(
      { detail: "Payload invalido. Envie um JSON com identity e password." } satisfies ApiErrorPayload,
      { status: 400 },
    ), requestId);
  }

  const identity = payload.identity?.trim() ?? "";
  const password = payload.password ?? "";

  if (!identity || !password) {
    return markSensitiveResponse(NextResponse.json(
      { detail: "Informe email e senha para continuar." } satisfies ApiErrorPayload,
      { status: 422 },
    ), requestId);
  }

  try {
    const loginResponse = await backendFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: identity,
        password,
      }),
    }, null, requestId);

    if (!loginResponse.ok) {
      const errorPayload =
        (await parseJsonResponse<ApiErrorPayload>(loginResponse)) ??
        ({ detail: "Falha ao autenticar." } satisfies ApiErrorPayload);

      return markSensitiveResponse(NextResponse.json(errorPayload, { status: loginResponse.status }), requestId);
    }

    const tokens = await parseJsonResponse<AuthTokens>(loginResponse);

    if (!tokens) {
      return json({ detail: "O backend retornou uma resposta de login vazia." }, 502);
    }

    const meResponse = await backendFetch("/auth/me", {}, tokens.access, requestId);
    const user = meResponse.ok ? await parseJsonResponse<User>(meResponse) : null;

    if (!user) {
      return json({ detail: "Nao foi possivel carregar o perfil autenticado." }, 502);
    }

    return markSensitiveResponse(jsonWithSession({ user }, { tokens }), requestId);
  } catch (cause) {
    if (cause instanceof BackendConfigurationError) {
      serverLogger.error("auth.login.backend_misconfigured", { requestId, route: "/api/auth/login", method: "POST", upstream: "judah", errorType: errorType(cause), status: 503 });
      return json({ detail: "Configuracao do servidor incompleta. Contate o administrador." }, 503);
    }
    if (cause instanceof BackendUnreachableError) {
      serverLogger.error("auth.login.backend_unreachable", { requestId, route: "/api/auth/login", method: "POST", upstream: "judah", errorType: errorType(cause), status: 502 });
      return json({ detail: "Backend Judah indisponivel no momento. Tente novamente em instantes." }, 502);
    }
    serverLogger.error("auth.login.unexpected_failure", { requestId, route: "/api/auth/login", method: "POST", errorType: errorType(cause), status: 500 });
    return json({ detail: "Erro interno ao processar o login." }, 500);
  }
}
