# OPS-01 — Retry and watchdog

- Webhook and AI Celery tasks use a bounded retry budget with exponential
  backoff.
- Celery Beat runs the lifecycle watchdog and due-retry dispatcher every
  minute.
- Stuck executions become `FAILED_RETRYABLE`.
- Due failures are redispatched; exhausted ticket-backed failures are handed
  to Matchmaker, while unroutable instances become `FAILED_TERMINAL`.
