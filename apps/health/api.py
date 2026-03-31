"""Health check endpoint for JUDAH."""

from datetime import datetime, timezone

from ninja import Router

router = Router()


@router.get("/", auth=None, summary="Health check")
def health_check(request) -> dict:
    """Return service health status.

    Checks database, Redis cache, and returns uptime metadata.
    """
    checks: dict[str, str] = {}

    try:
        from django.db import connection

        connection.ensure_connection()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    try:
        from django.core.cache import cache

        cache.set("health_ping", "pong", timeout=5)
        checks["cache"] = "ok" if cache.get("health_ping") == "pong" else "error"
    except Exception as exc:
        checks["cache"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())

    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "version": "1.0.0",
        "checks": checks,
    }
