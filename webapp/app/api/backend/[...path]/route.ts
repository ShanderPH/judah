import { NextResponse, type NextRequest } from "next/server";

import { hasCapability } from "@/src/lib/auth/access-policy";
import { evaluateBffRoute, isBodyWithinLimit, isJsonContentType, isTrustedMutation } from "@/src/lib/api/bff-policy";
import { BackendConfigurationError, BackendHttpError, BackendUnreachableError, backendFetch, refreshBackendTokens } from "@/src/lib/backend";
import { clearAuthCookies, readAuthTokens, resolveSessionFromTokens, writeAuthCookies } from "@/src/lib/auth/server-session";
import { markSensitiveResponse, resolveRequestId } from "@/src/lib/observability/request-context";
import { errorType, serverLogger } from "@/src/lib/observability/server-logger";
import type { ApiErrorPayload } from "@/src/types/api";

function error(detail: string, status: number, requestId: string): NextResponse {
  return markSensitiveResponse(NextResponse.json({ detail } satisfies ApiErrorPayload, { status }), requestId);
}

async function proxyRequest(request: NextRequest, context: { params: Promise<{ path: string[] }> }): Promise<NextResponse> {
  const requestId = resolveRequestId(request.headers);
  const { path } = await context.params;
  const pathname = `/${path.join("/")}/`;
  const policy = evaluateBffRoute(pathname, request.method);
  if (!policy.ok) return error(policy.status === 404 ? "Rota nao permitida." : "Metodo nao permitido.", policy.status, requestId);
  if (!isTrustedMutation(request)) return error("Origem da requisicao recusada.", 403, requestId);
  if (policy.requiresJson && !isJsonContentType(request.headers.get("content-type"))) return error("Content-Type deve ser application/json.", 415, requestId);

  const declaredLength = Number(request.headers.get("content-length") ?? 0);
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();
  if (!isBodyWithinLimit(declaredLength, body ?? "")) return error("Corpo da requisicao muito grande.", 413, requestId);

  try {
    const requestTokens = readAuthTokens(request.cookies);
    const session = await resolveSessionFromTokens(requestTokens, requestId);
    if (session.status !== "authenticated") {
      const response = error("Sessao expirada ou invalida.", 401, requestId);
      clearAuthCookies(response.cookies);
      return response;
    }
    if (!hasCapability(session.user, policy.capability)) return error("Permissao insuficiente.", 403, requestId);

    const forwardHeaders = new Headers({ "X-Request-ID": requestId });
    const contentType = request.headers.get("content-type");
    const idempotencyKey = request.headers.get("idempotency-key");
    if (contentType) forwardHeaders.set("Content-Type", contentType);
    if (idempotencyKey) forwardHeaders.set("Idempotency-Key", idempotencyKey);
    let responseTokens = session.tokens;
    let backendResponse = await backendFetch(
      `${pathname}${request.nextUrl.search}`,
      { method: request.method, body, headers: forwardHeaders },
      responseTokens?.access ?? requestTokens.accessToken,
      requestId,
    );
    const retryRefreshToken = responseTokens?.refresh ?? requestTokens.refreshToken;
    if (backendResponse.status === 401 && retryRefreshToken) {
      const refreshedTokens = await refreshBackendTokens(retryRefreshToken, requestId);
      if (refreshedTokens) {
        responseTokens = refreshedTokens;
        backendResponse = await backendFetch(
          `${pathname}${request.nextUrl.search}`,
          { method: request.method, body, headers: forwardHeaders },
          refreshedTokens.access,
          requestId,
        );
      }
    }
    const response = new NextResponse(await backendResponse.text(), { status: backendResponse.status });
    for (const header of ["content-type", "retry-after", "x-request-id", "x-ratelimit-limit", "x-ratelimit-remaining"]) {
      const value = backendResponse.headers.get(header);
      if (value) response.headers.set(header, value);
    }
    if (responseTokens) writeAuthCookies(response.cookies, responseTokens);
    if (backendResponse.status === 401) clearAuthCookies(response.cookies);
    return markSensitiveResponse(response, requestId);
  } catch (cause) {
    if (cause instanceof BackendHttpError) {
      const status = cause.status >= 500 ? 502 : cause.status;
      serverLogger.error("bff.backend_failure", { requestId, route: pathname, method: request.method, upstream: "judah", errorType: errorType(cause), status });
      return error("Backend Judah indisponivel no momento.", status, requestId);
    }
    if (cause instanceof BackendConfigurationError) {
      serverLogger.error("bff.backend_misconfigured", { requestId, route: pathname, method: request.method, upstream: "judah", errorType: errorType(cause), status: 503 });
      return error("Configuracao do servidor incompleta. Contate o administrador.", 503, requestId);
    }
    if (cause instanceof BackendUnreachableError) {
      serverLogger.error("bff.backend_unreachable", { requestId, route: pathname, method: request.method, upstream: "judah", errorType: errorType(cause), status: 502 });
      return error("Backend Judah indisponivel no momento.", 502, requestId);
    }
    serverLogger.error("bff.unexpected_failure", { requestId, route: pathname, method: request.method, errorType: errorType(cause), status: 500 });
    return error("Erro interno ao consultar o backend.", 500, requestId);
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PATCH = proxyRequest;
export const PUT = proxyRequest;
export const DELETE = proxyRequest;
