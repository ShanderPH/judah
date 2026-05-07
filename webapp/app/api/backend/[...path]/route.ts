import { NextResponse, type NextRequest } from "next/server";

import { AUTH_COOKIE_NAMES } from "@/src/lib/auth/constants";
import {
  BackendConfigurationError,
  BackendUnreachableError,
  backendFetch,
  refreshBackendTokens,
} from "@/src/lib/backend";
import { clearAuthCookies, writeAuthCookies } from "@/src/lib/auth/server-session";
import type { ApiErrorPayload } from "@/src/types/api";

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await context.params;
  const pathname = `/${path.join("/")}`;
  const search = request.nextUrl.search;
  const backendPath = `${pathname}${search}`;

  const accessToken = request.cookies.get(AUTH_COOKIE_NAMES.accessToken)?.value ?? null;
  const refreshToken = request.cookies.get(AUTH_COOKIE_NAMES.refreshToken)?.value ?? null;
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.text();

  const forward = async (token: string | null) =>
    backendFetch(
      backendPath,
      {
        method: request.method,
        body,
        headers: {
          "Content-Type": request.headers.get("content-type") ?? "application/json",
        },
      },
      token,
    );

  try {
    let backendResponse = await forward(accessToken);
    let refreshedTokens = null;

    if (backendResponse.status === 401 && refreshToken) {
      refreshedTokens = await refreshBackendTokens(refreshToken);

      if (refreshedTokens) {
        backendResponse = await forward(refreshedTokens.access);
      }
    }

    const response = new NextResponse(await backendResponse.text(), {
      status: backendResponse.status,
    });

    const passthroughHeaders = [
      "content-type",
      "retry-after",
      "x-request-id",
      "x-ratelimit-limit",
      "x-ratelimit-remaining",
    ];

    for (const header of passthroughHeaders) {
      const value = backendResponse.headers.get(header);
      if (value) {
        response.headers.set(header, value);
      }
    }

    if (refreshedTokens) {
      writeAuthCookies(response.cookies, refreshedTokens);
    } else if (backendResponse.status === 401) {
      clearAuthCookies(response.cookies);
    }

    return response;
  } catch (cause) {
    if (cause instanceof BackendConfigurationError) {
      console.error(`[api/backend${backendPath}] backend misconfigured`, cause);
      return NextResponse.json(
        { detail: "Configuracao do servidor incompleta. Contate o administrador." } satisfies ApiErrorPayload,
        { status: 503 },
      );
    }
    if (cause instanceof BackendUnreachableError) {
      console.error(`[api/backend${backendPath}] backend unreachable`, cause.cause ?? cause);
      return NextResponse.json(
        { detail: "Backend Judah indisponivel no momento. Tente novamente em instantes." } satisfies ApiErrorPayload,
        { status: 502 },
      );
    }
    console.error(`[api/backend${backendPath}] unexpected failure`, cause);
    return NextResponse.json(
      { detail: "Erro interno ao consultar o backend." } satisfies ApiErrorPayload,
      { status: 500 },
    );
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PATCH = proxyRequest;
export const PUT = proxyRequest;
export const DELETE = proxyRequest;
