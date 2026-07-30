import "server-only";

import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAMES } from "@/src/lib/auth/constants";
import { fetchCurrentUser, refreshBackendTokens } from "@/src/lib/backend";
import type { AuthTokens, User } from "@/src/types/api";
import { TOKEN_FALLBACK_MAX_AGE, isExpiredToken, tokenMaxAge } from "@/src/lib/auth/token-policy";

interface CookieEntry {
  value: string;
}

interface CookieReader {
  get(name: string): CookieEntry | undefined;
}

interface CookieMutator {
  set(
    name: string,
    value: string,
    options: {
      httpOnly: boolean;
      maxAge: number;
      path: string;
      sameSite: "lax";
      secure: boolean;
    },
  ): void;
  delete(name: string): void;
}

export type SessionResult =
  | { status: "authenticated"; user: User; tokens: AuthTokens | null }
  | { status: "expired" | "invalid" | "missing"; user: null; tokens: null };

const cookieOptions = {
  path: "/",
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
};

export function readAuthTokens(source: CookieReader): {
  accessToken: string | null;
  refreshToken: string | null;
} {
  return {
    accessToken: source.get(AUTH_COOKIE_NAMES.accessToken)?.value ?? null,
    refreshToken: source.get(AUTH_COOKIE_NAMES.refreshToken)?.value ?? null,
  };
}

export function writeAuthCookies(target: CookieMutator, tokens: AuthTokens): void {
  target.set(AUTH_COOKIE_NAMES.accessToken, tokens.access, {
    ...cookieOptions,
    maxAge: tokenMaxAge(tokens.access, TOKEN_FALLBACK_MAX_AGE.access),
  });
  target.set(AUTH_COOKIE_NAMES.refreshToken, tokens.refresh, {
    ...cookieOptions,
    maxAge: tokenMaxAge(tokens.refresh, TOKEN_FALLBACK_MAX_AGE.refresh),
  });
}

export function clearAuthCookies(target: CookieMutator): void {
  target.delete(AUTH_COOKIE_NAMES.accessToken);
  target.delete(AUTH_COOKIE_NAMES.refreshToken);
}

export async function resolveSessionFromTokens(tokens: {
  accessToken: string | null;
  refreshToken: string | null;
}, requestId?: string): Promise<SessionResult> {
  if (tokens.accessToken) {
    const user = await fetchCurrentUser(tokens.accessToken, requestId);

    if (user) {
      return {
        status: "authenticated",
        user,
        tokens:
          tokens.refreshToken === null
            ? null
            : {
                access: tokens.accessToken,
                refresh: tokens.refreshToken,
              },
      };
    }
  }

  if (!tokens.refreshToken) {
    if (!tokens.accessToken) return { status: "missing", user: null, tokens: null };
    return {
      status: isExpiredToken(tokens.accessToken) ? "expired" : "invalid",
      user: null,
      tokens: null,
    };
  }

  const refreshedTokens = await refreshBackendTokens(tokens.refreshToken, requestId);

  if (!refreshedTokens) {
    return { status: "invalid", user: null, tokens: null };
  }

  const user = await fetchCurrentUser(refreshedTokens.access, requestId);

  if (!user) {
    return { status: "invalid", user: null, tokens: null };
  }

  return {
    status: "authenticated",
    user,
    tokens: refreshedTokens,
  };
}

export function jsonWithSession<T>(
  payload: T,
  options?: {
    clearCookies?: boolean;
    tokens?: AuthTokens | null;
    status?: number;
  },
): NextResponse {
  const response = NextResponse.json(payload, { status: options?.status ?? 200 });
  response.headers.set("Cache-Control", "private, no-cache, no-store, max-age=0, must-revalidate");

  if (options?.tokens) {
    writeAuthCookies(response.cookies, options.tokens);
  }

  if (options?.clearCookies) {
    clearAuthCookies(response.cookies);
  }

  return response;
}
