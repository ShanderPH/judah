import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { readAuthTokens, resolveSessionFromTokens, writeAuthCookies, clearAuthCookies } from "@/src/lib/auth/server-session";

function safeNext(value: string | null): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const session = await resolveSessionFromTokens(readAuthTokens(cookieStore));
  if (session.status !== "authenticated") {
    const response = NextResponse.redirect(new URL("/login", request.url));
    clearAuthCookies(response.cookies);
    return response;
  }
  const response = NextResponse.redirect(new URL(safeNext(request.nextUrl.searchParams.get("next")), request.url));
  if (session.tokens) writeAuthCookies(response.cookies, session.tokens);
  return response;
}
