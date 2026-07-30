import type { PaginatedResponse } from "@/src/types/api";

interface PaginationQuery {
  limit?: number | string;
  offset?: number | string;
}

interface PaginationContext {
  path?: string;
  query?: PaginationQuery;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function nonNegativeInteger(value: unknown, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function pageLink(path: string | undefined, limit: number, offset: number): string {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return `${path ?? ""}?${query.toString()}`;
}

/** Normalize Django Ninja and legacy pagination envelopes at the transport boundary. */
export function normalizePaginatedResponse<T>(
  raw: unknown,
  context: PaginationContext = {},
): PaginatedResponse<T> {
  if (!isRecord(raw)) {
    throw new TypeError("Invalid paginated response: expected an object.");
  }

  const rawItems = Array.isArray(raw.results) ? raw.results : raw.items;
  if (!Array.isArray(rawItems)) {
    throw new TypeError("Invalid paginated response: expected results or items array.");
  }

  const results = rawItems as T[];
  const count = nonNegativeInteger(raw.count, results.length);
  const limit = Math.max(1, nonNegativeInteger(context.query?.limit, results.length || 20));
  const offset = nonNegativeInteger(context.query?.offset, 0);

  const suppliedNext = typeof raw.next === "string" ? raw.next : null;
  const suppliedPrevious = typeof raw.previous === "string" ? raw.previous : null;
  const usesNinjaEnvelope = Array.isArray(raw.items) && !Array.isArray(raw.results);

  return {
    count,
    next:
      suppliedNext ??
      (usesNinjaEnvelope && offset + results.length < count
        ? pageLink(context.path, limit, offset + limit)
        : null),
    previous:
      suppliedPrevious ??
      (usesNinjaEnvelope && offset > 0
        ? pageLink(context.path, limit, Math.max(0, offset - limit))
        : null),
    results,
  };
}
