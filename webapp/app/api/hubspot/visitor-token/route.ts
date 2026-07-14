import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";

export const dynamic = "force-dynamic";

interface HubSpotVisitorTokenResponse {
  expiresAt: string;
  token: string;
}

/**
 * Creates a short-lived HubSpot Visitor Identification token for the signed-in
 * Judah user. The HubSpot private-app/OAuth token stays server-side.
 */
export async function POST() {
  const accessToken = process.env.HUBSPOT_SANDBOX_OAUTH_ACCESS_TOKEN;

  if (!accessToken) {
    return NextResponse.json(
      { detail: "HUBSPOT_SANDBOX_OAUTH_ACCESS_TOKEN nao foi configurado no servidor." },
      { status: 503 },
    );
  }

  const cookieStore = await cookies();
  const session = await resolveSessionFromTokens(readAuthTokens(cookieStore));

  if (!session.user) {
    return NextResponse.json({ detail: "Sessao expirada." }, { status: 401 });
  }

  try {
    const response = await fetch("https://api.hubapi.com/conversations/v3/visitor-identification/tokens", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        visitorId: `judah-sandbox-user-${session.user.id}`,
        expiresInMins: 60,
      }),
      cache: "no-store",
    });

    if (!response.ok) {
      const body = await response.text();
      console.error("[hubspot/visitor-token] HubSpot rejected token request", {
        status: response.status,
        body: body.slice(0, 500),
      });
      return NextResponse.json(
        { detail: "Nao foi possivel autenticar o visitante no HubSpot." },
        { status: 502 },
      );
    }

    const payload = (await response.json()) as HubSpotVisitorTokenResponse;
    return NextResponse.json({ expiresAt: payload.expiresAt, token: payload.token });
  } catch (error) {
    console.error("[hubspot/visitor-token] request failed", error);
    return NextResponse.json({ detail: "HubSpot indisponivel no momento." }, { status: 502 });
  }
}
