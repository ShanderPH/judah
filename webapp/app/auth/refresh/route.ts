import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { readAuthTokens, resolveSessionFromTokens, writeAuthCookies, clearAuthCookies } from "@/src/lib/auth/server-session";

function safeNext(value: string | null, baseUrl: string): URL {
  const base = new URL(baseUrl);
  const fallback = new URL("/dashboard", base);
  if (!value?.startsWith("/") || value.startsWith("//")) return fallback;

  try {
    // Reject malformed input once; literal percent signs after decoding are valid.
    decodeURIComponent(value);
    // Validate decoded forms too; retain the original encoding in valid redirects.
    let candidate = value;
    while (true) {
      if ([...candidate].some((char) => char === "\\" || char.charCodeAt(0) <= 31 || char.charCodeAt(0) === 127)) {
        return fallback;
      }
      const resolved = new URL(candidate, base);
      if (
        !["http:", "https:"].includes(resolved.protocol) ||
        resolved.origin !== base.origin ||
        !resolved.pathname.startsWith("/") ||
        resolved.pathname.startsWith("//")
      ) return fallback;
      const decoded = candidate.replace(/%([0-9a-f]{2})/gi, (_, hex: string) =>
        String.fromCharCode(Number.parseInt(hex, 16)),
      );
      if (decoded === candidate) break;
      candidate = decoded;
    }
    return new URL(value, base);
  } catch {
    return fallback;
  }
}

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const session = await resolveSessionFromTokens(readAuthTokens(cookieStore));
  if (session.status !== "authenticated") {
    const response = NextResponse.redirect(new URL("/login", request.url));
    clearAuthCookies(response.cookies);
    return response;
  }
  const response = NextResponse.redirect(safeNext(request.nextUrl.searchParams.get("next"), request.url));
  if (session.tokens) writeAuthCookies(response.cookies, session.tokens);
  return response;
}
