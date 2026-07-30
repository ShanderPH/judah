import "server-only";

import { sanitizeLogFields, type SafeLogFields } from "@/src/lib/observability/log-policy";

type LogLevel = "error" | "info" | "warn";

function write(level: LogLevel, event: string, fields: SafeLogFields): void {
  const record = JSON.stringify({
    timestamp: new Date().toISOString(),
    level,
    event: event.replace(/[^a-z0-9_.-]/gi, "_").slice(0, 80),
    service: "judah-webapp",
    ...sanitizeLogFields(fields),
  });

  if (level === "error") console.error(record);
  else if (level === "warn") console.warn(record);
  else console.info(record);
}

export const serverLogger = {
  error: (event: string, fields: SafeLogFields = {}) => write("error", event, fields),
  info: (event: string, fields: SafeLogFields = {}) => write("info", event, fields),
  warn: (event: string, fields: SafeLogFields = {}) => write("warn", event, fields),
};

export function errorType(cause: unknown): string {
  return cause instanceof Error ? cause.name : "UnknownError";
}
