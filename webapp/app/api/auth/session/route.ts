import { cookies } from "next/headers";

import {
  BackendConfigurationError,
  BackendUnreachableError,
} from "@/src/lib/backend";
import { jsonWithSession, readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";
import type { ApiErrorPayload } from "@/src/types/api";

export async function GET() {
  const cookieStore = await cookies();

  try {
    const session = await resolveSessionFromTokens(readAuthTokens(cookieStore));

    if (!session.user) {
      return jsonWithSession(
        { detail: "Sessao expirada." } satisfies ApiErrorPayload,
        { clearCookies: true, status: 401 },
      );
    }

    return jsonWithSession({ user: session.user }, { tokens: session.tokens });
  } catch (cause) {
    if (cause instanceof BackendConfigurationError) {
      console.error("[auth/session] backend misconfigured", cause);
      return jsonWithSession(
        { detail: "Configuracao do servidor incompleta. Contate o administrador." } satisfies ApiErrorPayload,
        { status: 503 },
      );
    }
    if (cause instanceof BackendUnreachableError) {
      console.error("[auth/session] backend unreachable", cause.cause ?? cause);
      return jsonWithSession(
        { detail: "Backend Judah indisponivel no momento." } satisfies ApiErrorPayload,
        { status: 502 },
      );
    }
    console.error("[auth/session] unexpected failure", cause);
    return jsonWithSession(
      { detail: "Erro interno ao validar a sessao." } satisfies ApiErrorPayload,
      { status: 500 },
    );
  }
}
