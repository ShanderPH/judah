import { NextResponse, type NextRequest } from "next/server";

import { AUTH_COOKIE_NAMES } from "@/src/lib/auth/constants";

const protectedPrefixes = ["/dashboard", "/queue", "/auto-assignment", "/metrics", "/sandbox-chat"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (pathname.startsWith("/api") || pathname.startsWith("/_next")) {
    return NextResponse.next();
  }

  const hasSession =
    request.cookies.has(AUTH_COOKIE_NAMES.accessToken) ||
    request.cookies.has(AUTH_COOKIE_NAMES.refreshToken);

  const isProtected = protectedPrefixes.some((prefix) => pathname.startsWith(prefix));

  if (isProtected && !hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  if (pathname === "/login" && hasSession) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
