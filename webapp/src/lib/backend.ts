import "server-only";

import { isCredentialRejectionStatus } from "@/src/lib/auth/upstream-status";
import type { AuthTokens, User } from "@/src/types/api";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000/api/v1";

export class BackendConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BackendConfigurationError";
  }
}

export class BackendUnreachableError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "BackendUnreachableError";
  }
}

export class BackendHttpError extends Error {
  status: number;

  constructor(path: string, status: number) {
    super(`Judah respondeu ${status} para ${path}.`);
    this.name = "BackendHttpError";
    this.status = status;
  }
}

function resolveBackendApiUrl(): string {
  const raw = process.env.JUDAH_API_URL;
  if (!raw || raw.trim() === "") {
    if (process.env.NODE_ENV === "production") {
      throw new BackendConfigurationError(
        "JUDAH_API_URL nao esta definido. Configure a variavel de ambiente apontando para o backend Judah em producao.",
      );
    }
    return DEFAULT_BACKEND_URL;
  }
  return raw.replace(/\/$/, "");
}

function buildBackendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${resolveBackendApiUrl()}${normalizedPath}`;
}

export async function backendFetch(
  path: string,
  init: RequestInit = {},
  accessToken?: string | null,
  requestId?: string,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  if (!headers.has("X-Request-ID")) {
    headers.set("X-Request-ID", requestId ?? crypto.randomUUID());
  }

  try {
    return await fetch(buildBackendUrl(path), {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch (cause) {
    if (cause instanceof BackendConfigurationError) {
      throw cause;
    }
    throw new BackendUnreachableError(
      "Nao foi possivel contatar o backend Judah.",
      cause,
    );
  }
}

export async function parseJsonResponse<T>(response: Response): Promise<T | null> {
  const text = await response.text();

  if (!text) {
    return null;
  }

  return JSON.parse(text) as T;
}

export async function refreshBackendTokens(refreshToken: string, requestId?: string): Promise<AuthTokens | null> {
  const response = await backendFetch("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh: refreshToken }),
  }, null, requestId);

  if (isCredentialRejectionStatus(response.status)) return null;
  if (!response.ok) throw new BackendHttpError("/auth/refresh", response.status);

  return parseJsonResponse<AuthTokens>(response);
}

export async function fetchCurrentUser(accessToken: string, requestId?: string): Promise<User | null> {
  const response = await backendFetch("/auth/me", {}, accessToken, requestId);

  if (isCredentialRejectionStatus(response.status)) return null;
  if (!response.ok) throw new BackendHttpError("/auth/me", response.status);

  return parseJsonResponse<User>(response);
}
