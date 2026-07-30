const SECRET_PATTERN = /(bearer\s+\S+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|password|access[_-]?token|refresh[_-]?token|authorization|cookie)/gi;

export interface SafeLogFields {
  errorType?: string;
  method?: string;
  outcome?: string;
  requestId?: string;
  route?: string;
  status?: number;
  upstream?: "judah" | "hubspot";
}

export function redactLogValue(value: string): string {
  return value.replace(SECRET_PATTERN, "[REDACTED]").slice(0, 256);
}

export function sanitizeLogFields(fields: SafeLogFields): SafeLogFields {
  return Object.fromEntries(
    Object.entries(fields).map(([key, value]) => [
      key,
      typeof value === "string" ? redactLogValue(value) : value,
    ]),
  ) as SafeLogFields;
}
