const REQUEST_ID_PATTERN = /^[A-Za-z0-9._:-]{8,128}$/;

export function resolveRequestId(headers: Headers): string {
  const supplied = headers.get("x-request-id");
  return supplied && REQUEST_ID_PATTERN.test(supplied) ? supplied : crypto.randomUUID();
}

export function attachRequestId<T extends Response>(response: T, requestId: string): T {
  response.headers.set("X-Request-ID", requestId);
  return response;
}

export function markSensitiveResponse<T extends Response>(response: T, requestId: string): T {
  response.headers.set("Cache-Control", "private, no-cache, no-store, max-age=0, must-revalidate");
  return attachRequestId(response, requestId);
}
