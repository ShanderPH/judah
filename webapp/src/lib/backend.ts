import "server-only";

import type { AuthTokens, User } from "@/src/types/api";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000/api/v1";

const backendApiUrl = (process.env.JUDAH_API_URL ?? DEFAULT_BACKEND_URL).replace(/\/$/, "");

function buildBackendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${backendApiUrl}${normalizedPath}`;
}

export async function backendFetch(
  path: string,
  init: RequestInit = {},
  accessToken?: string | null,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  return fetch(buildBackendUrl(path), {
    ...init,
    headers,
    cache: "no-store",
  });
}

export async function parseJsonResponse<T>(response: Response): Promise<T | null> {
  const text = await response.text();

  if (!text) {
    return null;
  }

  return JSON.parse(text) as T;
}

export async function refreshBackendTokens(refreshToken: string): Promise<AuthTokens | null> {
  const response = await backendFetch(
    `/auth/refresh?refresh=${encodeURIComponent(refreshToken)}`,
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    return null;
  }

  return parseJsonResponse<AuthTokens>(response);
}

export async function fetchCurrentUser(accessToken: string): Promise<User | null> {
  const response = await backendFetch("/auth/me", {}, accessToken);

  if (!response.ok) {
    return null;
  }

  return parseJsonResponse<User>(response);
}
