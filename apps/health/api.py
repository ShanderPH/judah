"""Health check endpoint for JUDAH."""

from datetime import UTC, datetime

from django.http import JsonResponse
from ninja import Router

router = Router()


@router.get("/", auth=None, summary="Liveness probe")
def health_check(request) -> dict:
    """Liveness probe — always 200 if the process is running.

    Used by Railway / k8s liveness probes which only need to know whether
    the process is alive, *not* whether dependencies are healthy.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "version": "1.0.0",
    }


@router.get("/ready", auth=None, summary="Readiness probe")
def readiness_check(request) -> JsonResponse:
    """Readiness probe — verifies DB + cache + auth-critical migrations.

    Returns 503 (not 200) if any critical dependency is degraded so
    upstream load balancers stop routing traffic until recovery.
    """
    checks: dict[str, str] = {}

    try:
        from django.db import connection

        connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    try:
        from django.core.cache import cache

        cache.set("health_ping", "pong", timeout=5)
        checks["cache"] = "ok" if cache.get("health_ping") == "pong" else "error"
    except Exception as exc:
        checks["cache"] = f"error: {exc}"

    # Verify auth-critical tables exist — these are the ones whose absence
    # surfaces as a silent 500 on /auth/login when token_blacklist or
    # auth_users migrations failed to apply.
    try:
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('public.auth_users'), to_regclass('public.token_blacklist_outstandingtoken')",
            )
            row = cur.fetchone() or (None, None)
        if row[0] is None:
            checks["auth_schema"] = "error: auth_users table missing"
        elif row[1] is None:
            checks["auth_schema"] = "error: token_blacklist tables missing"
        else:
            checks["auth_schema"] = "ok"
    except Exception as exc:
        checks["auth_schema"] = f"error: {exc}"

    # Replicate the exact failure path of /auth/login without persisting
    # anything: encode an access token for the first available user. This
    # exposes signing-key issues (HS256 needs a non-empty SECRET_KEY) and
    # any blacklist-app issue that doesn't manifest as a missing table.
    try:
        from ninja_jwt.tokens import AccessToken

        from apps.auth_user.models import User

        u = User.objects.only("id").first()
        if u is None:
            checks["jwt_mint"] = "skipped: no users"
        else:
            token = AccessToken.for_user(u)
            _ = str(token)
            checks["jwt_mint"] = "ok"
    except Exception as exc:
        checks["jwt_mint"] = f"error: {type(exc).__name__}: {exc}"

    all_ok = all(v == "ok" or v.startswith("skipped") for v in checks.values())
    body = {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "version": "1.0.0",
        "checks": checks,
    }
    return JsonResponse(body, status=200 if all_ok else 503)
