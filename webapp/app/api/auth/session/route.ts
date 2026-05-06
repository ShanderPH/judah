import { cookies } from "next/headers";

import { jsonWithSession, readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";

export async function GET() {
  const cookieStore = await cookies();
  const session = await resolveSessionFromTokens(readAuthTokens(cookieStore));

  if (!session.user) {
    return jsonWithSession(
      {
        detail: "Sessao expirada.",
      },
      {
        clearCookies: true,
        status: 401,
      },
    );
  }

  return jsonWithSession(
    {
      user: session.user,
    },
    {
      tokens: session.tokens,
    },
  );
}
