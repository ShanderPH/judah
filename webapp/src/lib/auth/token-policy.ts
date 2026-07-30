const DEFAULT_ACCESS_MAX_AGE = 5 * 60;
const DEFAULT_REFRESH_MAX_AGE = 24 * 60 * 60;

function decodePayload(token: string): { exp?: unknown } | null {
  try {
    const encoded = token.split(".")[1];
    if (!encoded) return null;
    const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(normalized)) as unknown;
    return typeof payload === "object" && payload !== null ? payload : null;
  } catch {
    return null;
  }
}

export function tokenMaxAge(token: string, fallback: number, now = Date.now()): number {
  const payload = decodePayload(token);
  if (typeof payload?.exp !== "number") return fallback;
  return Math.max(0, Math.floor(payload.exp - now / 1000));
}

export function isExpiredToken(token: string, now = Date.now()): boolean {
  const payload = decodePayload(token);
  return typeof payload?.exp === "number" && payload.exp <= now / 1000;
}

export const TOKEN_FALLBACK_MAX_AGE = {
  access: DEFAULT_ACCESS_MAX_AGE,
  refresh: DEFAULT_REFRESH_MAX_AGE,
} as const;
