import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";

export const dynamic = "force-dynamic";

interface HubSpotVisitorTokenResponse {
  token: string;
}

/**
 * Creates a short-lived HubSpot Visitor Identification token for the signed-in
 * Judah user. The HubSpot private-app/OAuth token stays server-side.
 */
export async function POST() {
  const accessToken =
    process.env.HUBSPOT_SANDBOX_ACCESS_TOKEN ?? process.env.HUBSPOT_SANDBOX_OAUTH_ACCESS_TOKEN;

  if (!accessToken) {
    return NextResponse.json(
      { detail: "HUBSPOT_SANDBOX_ACCESS_TOKEN nao foi configurado no servidor." },
      { status: 503 },
    );
  }

  const cookieStore = await cookies();
  const session = await resolveSessionFromTokens(readAuthTokens(cookieStore));

  if (!session.user) {
    return NextResponse.json({ detail: "Sessao expirada." }, { status: 401 });
  }

  try {
    const response = await fetch("https://api.hubapi.com/visitor-identification/v3/tokens/create", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
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
      const body = await response.text();
      console.error("[hubspot/visitor-token] HubSpot rejected token request", {
        status: response.status,
        body: body.slice(0, 500),
      });
      const detail =
        response.status === 401
          ? "O token de acesso da sandbox HubSpot e invalido ou expirou."
          : response.status === 403
            ? "O app nao possui o escopo necessario ou a conta sandbox nao tem assinatura HubSpot Professional/Enterprise."
            : "Nao foi possivel autenticar o visitante no HubSpot.";
      return NextResponse.json({ detail }, { status: 502 });
    }

    const payload = (await response.json()) as HubSpotVisitorTokenResponse;
    return NextResponse.json({ token: payload.token });
  } catch (error) {
    console.error("[hubspot/visitor-token] request failed", error);
    return NextResponse.json({ detail: "HubSpot indisponivel no momento." }, { status: 502 });
  }
}
