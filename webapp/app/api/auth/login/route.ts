import { NextResponse, type NextRequest } from "next/server";

import { backendFetch, parseJsonResponse } from "@/src/lib/backend";
import { jsonWithSession } from "@/src/lib/auth/server-session";
import type { ApiErrorPayload, AuthTokens, User } from "@/src/types/api";

interface LoginRequestPayload {
  identity?: string;
  password?: string;
}

export async function POST(request: NextRequest) {
  const payload = (await request.json()) as LoginRequestPayload;
  const identity = payload.identity?.trim() ?? "";
  const password = payload.password ?? "";

  if (!identity || !password) {
    return NextResponse.json(
      {
        detail: "Informe email e senha para continuar.",
      } satisfies ApiErrorPayload,
      { status: 422 },
    );
  }

  const loginResponse = await backendFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({
      username: identity,
      password,
    }),
  });

  if (!loginResponse.ok) {
    const errorPayload =
      (await parseJsonResponse<ApiErrorPayload>(loginResponse)) ?? ({ detail: "Falha ao autenticar." } satisfies ApiErrorPayload);

    return NextResponse.json(errorPayload, {
      status: loginResponse.status,
    });
  }

  const tokens = await parseJsonResponse<AuthTokens>(loginResponse);

  if (!tokens) {
    return NextResponse.json(
      {
        detail: "O backend retornou uma resposta de login vazia.",
      } satisfies ApiErrorPayload,
      { status: 502 },
    );
  }

  const meResponse = await backendFetch("/auth/me", {}, tokens.access);
  const user =
    meResponse.ok ? await parseJsonResponse<User>(meResponse) : null;

  if (!user) {
    return NextResponse.json(
      {
        detail: "Nao foi possivel carregar o perfil autenticado.",
      } satisfies ApiErrorPayload,
      { status: 502 },
    );
  }

  return jsonWithSession({ user }, { tokens });
}
