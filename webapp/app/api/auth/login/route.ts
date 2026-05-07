import { NextResponse, type NextRequest } from "next/server";

import {
  BackendConfigurationError,
  BackendUnreachableError,
  backendFetch,
  parseJsonResponse,
} from "@/src/lib/backend";
import { jsonWithSession } from "@/src/lib/auth/server-session";
import type { ApiErrorPayload, AuthTokens, User } from "@/src/types/api";

interface LoginRequestPayload {
  identity?: string;
  password?: string;
}

export async function POST(request: NextRequest) {
  let payload: LoginRequestPayload;
  try {
    payload = (await request.json()) as LoginRequestPayload;
  } catch {
    return NextResponse.json(
      { detail: "Payload invalido. Envie um JSON com identity e password." } satisfies ApiErrorPayload,
      { status: 400 },
    );
  }

  const identity = payload.identity?.trim() ?? "";
  const password = payload.password ?? "";

  if (!identity || !password) {
    return NextResponse.json(
      { detail: "Informe email e senha para continuar." } satisfies ApiErrorPayload,
      { status: 422 },
    );
  }

  try {
    const loginResponse = await backendFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: identity,
        password,
      }),
    });

    if (!loginResponse.ok) {
      const errorPayload =
        (await parseJsonResponse<ApiErrorPayload>(loginResponse)) ??
        ({ detail: "Falha ao autenticar." } satisfies ApiErrorPayload);

      return NextResponse.json(errorPayload, {
        status: loginResponse.status,
      });
    }

    const tokens = await parseJsonResponse<AuthTokens>(loginResponse);

    if (!tokens) {
      return NextResponse.json(
        { detail: "O backend retornou uma resposta de login vazia." } satisfies ApiErrorPayload,
        { status: 502 },
      );
    }

    const meResponse = await backendFetch("/auth/me", {}, tokens.access);
    const user = meResponse.ok ? await parseJsonResponse<User>(meResponse) : null;

    if (!user) {
      return NextResponse.json(
        { detail: "Nao foi possivel carregar o perfil autenticado." } satisfies ApiErrorPayload,
        { status: 502 },
      );
    }

    return jsonWithSession({ user }, { tokens });
  } catch (cause) {
    if (cause instanceof BackendConfigurationError) {
      console.error("[auth/login] backend misconfigured", cause);
      return NextResponse.json(
        { detail: "Configuracao do servidor incompleta. Contate o administrador." } satisfies ApiErrorPayload,
        { status: 503 },
      );
    }
    if (cause instanceof BackendUnreachableError) {
      console.error("[auth/login] backend unreachable", cause.cause ?? cause);
      return NextResponse.json(
        { detail: "Backend Judah indisponivel no momento. Tente novamente em instantes." } satisfies ApiErrorPayload,
        { status: 502 },
      );
    }
    console.error("[auth/login] unexpected failure", cause);
    return NextResponse.json(
      { detail: "Erro interno ao processar o login." } satisfies ApiErrorPayload,
      { status: 500 },
    );
  }
}
