import "server-only";

import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAMES } from "@/src/lib/auth/constants";
import { fetchCurrentUser, refreshBackendTokens } from "@/src/lib/backend";
import type { AuthTokens, User } from "@/src/types/api";

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

interface SessionResult {
  user: User | null;
  tokens: AuthTokens | null;
}

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
    maxAge: 60 * 60,
  });
  target.set(AUTH_COOKIE_NAMES.refreshToken, tokens.refresh, {
    ...cookieOptions,
    maxAge: 60 * 60 * 24 * 7,
  });
}

export function clearAuthCookies(target: CookieMutator): void {
  target.delete(AUTH_COOKIE_NAMES.accessToken);
  target.delete(AUTH_COOKIE_NAMES.refreshToken);
}

export async function resolveSessionFromTokens(tokens: {
  accessToken: string | null;
  refreshToken: string | null;
}): Promise<SessionResult> {
  if (tokens.accessToken) {
    const user = await fetchCurrentUser(tokens.accessToken);

    if (user) {
      return {
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
    return { user: null, tokens: null };
  }

  const refreshedTokens = await refreshBackendTokens(tokens.refreshToken);

  if (!refreshedTokens) {
    return { user: null, tokens: null };
  }

  const user = await fetchCurrentUser(refreshedTokens.access);

  if (!user) {
    return { user: null, tokens: null };
  }

  return {
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

  if (options?.tokens) {
    writeAuthCookies(response.cookies, options.tokens);
  }

  if (options?.clearCookies) {
    clearAuthCookies(response.cookies);
  }

  return response;
}
