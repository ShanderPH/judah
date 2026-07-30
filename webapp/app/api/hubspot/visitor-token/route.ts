import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";
import { markSensitiveResponse, resolveRequestId } from "@/src/lib/observability/request-context";
import { errorType, serverLogger } from "@/src/lib/observability/server-logger";

export const dynamic = "force-dynamic";

interface HubSpotVisitorTokenResponse {
  token: string;
}

/**
 * Creates a short-lived HubSpot Visitor Identification token for the signed-in
 * Judah user. The HubSpot private-app/OAuth token stays server-side.
 */
export async function POST(request: NextRequest) {
  const requestId = resolveRequestId(request.headers);
  const json = (payload: object, status = 200) =>
    markSensitiveResponse(NextResponse.json(payload, { status }), requestId);
  const accessToken =
    process.env.HUBSPOT_SANDBOX_ACCESS_TOKEN ?? process.env.HUBSPOT_SANDBOX_OAUTH_ACCESS_TOKEN;

  if (!accessToken) {
    serverLogger.error("hubspot.visitor_token.misconfigured", { requestId, route: "/api/hubspot/visitor-token", method: "POST", upstream: "hubspot", status: 503 });
    return json({ detail: "HUBSPOT_SANDBOX_ACCESS_TOKEN nao foi configurado no servidor." }, 503);
  }

  try {
    const cookieStore = await cookies();
    const session = await resolveSessionFromTokens(readAuthTokens(cookieStore), requestId);

    if (session.status !== "authenticated") {
      return json({ detail: "Sessao expirada." }, 401);
    }

    const response = await fetch("https://api.hubapi.com/visitor-identification/v3/tokens/create", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body: JSON.stringify({
        email: session.user.email,
        firstName: session.user.first_name || undefined,
        lastName: session.user.last_name || undefined,
        hsCustomerAgentContext: {
          judahUserId: String(session.user.id),
          source: "judah-sandbox-chat",
        },
      }),
      cache: "no-store",
    });

    if (!response.ok) {
      serverLogger.error("hubspot.visitor_token.rejected", { requestId, route: "/api/hubspot/visitor-token", method: "POST", upstream: "hubspot", status: response.status });
      const detail =
        response.status === 401
          ? "O token de acesso da sandbox HubSpot e invalido ou expirou."
          : response.status === 403
            ? "O app nao possui o escopo necessario ou a conta sandbox nao tem assinatura HubSpot Professional/Enterprise."
            : "Nao foi possivel autenticar o visitante no HubSpot.";
      return json({ detail }, 502);
    }

    const payload = (await response.json()) as HubSpotVisitorTokenResponse;
    return json({ token: payload.token });
  } catch (cause) {
    serverLogger.error("hubspot.visitor_token.unreachable", { requestId, route: "/api/hubspot/visitor-token", method: "POST", upstream: "hubspot", errorType: errorType(cause), status: 502 });
    return json({ detail: "HubSpot indisponivel no momento." }, 502);
  }
}
