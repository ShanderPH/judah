"""Tests for liveness and readiness probes."""

import json
from contextlib import nullcontext
from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory
from structlog.testing import capture_logs

from apps.health.api import health_check, readiness_check


def test_liveness_returns_process_metadata() -> None:
    response = health_check(None)
    assert response["status"] == "alive"
    assert response["version"] == "1.0.0"
    assert response["timestamp"]


def test_assignment_failure_does_not_change_liveness() -> None:
    with patch(
        "apps.support.assignment_readiness.evaluate_assignment_readiness",
        side_effect=RuntimeError("assignment unavailable"),
    ):
        response = health_check(None)

    assert response["status"] == "alive"


def test_readiness_returns_healthy_when_dependencies_pass() -> None:
    cursor = Mock()
    cursor.fetchone.side_effect = [(1,), ("auth_users", "token_blacklist_outstandingtoken")]
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    cache = Mock()
    cache.get.return_value = "pong"
    user_manager = Mock()
    user_manager.only.return_value.first.return_value = None

    with (
        patch("django.db.connection", connection),
        patch("django.core.cache.cache", cache),
        patch("apps.auth_user.models.User.objects", user_manager),
    ):
        response = readiness_check(None)

    assert response.status_code == 200
    assert b'"status": "healthy"' in response.content
    assert b'"jwt_mint": "skipped: no users"' in response.content


def test_readiness_returns_degraded_when_dependencies_fail() -> None:
    connection = Mock()
    connection.ensure_connection.side_effect = RuntimeError("db down")
    connection.cursor.side_effect = RuntimeError("schema unavailable")
    cache = Mock()
    cache.set.side_effect = RuntimeError("cache down")
    user_manager = Mock()
    user_manager.only.return_value.first.return_value = object()

    with (
        patch("django.db.connection", connection),
        patch("django.core.cache.cache", cache),
        patch("apps.auth_user.models.User.objects", user_manager),
        patch("ninja_jwt.tokens.AccessToken.for_user", side_effect=RuntimeError("jwt broken")),
    ):
        response = readiness_check(None)

    assert response.status_code == 503
    assert b'"status": "degraded"' in response.content
    assert json.loads(response.content)["checks"] == {
        "database": "error",
        "cache": "error",
        "auth_schema": "error",
        "jwt_mint": "error",
    }
    for marker in (b"db down", b"cache down", b"jwt broken", b"schema unavailable", b"RuntimeError"):
        assert marker not in response.content
        assert marker.decode() not in str(response.headers)


@pytest.mark.parametrize("failed_check", ["database", "cache", "auth_schema", "jwt_mint", "conversation_cycles"])
def test_probe_failures_have_safe_public_values_and_internal_context(failed_check: str) -> None:
    """Keep diagnostics useful internally without reflecting exception text or secrets."""
    marker = "postgres://synthetic:password@private.invalid:5432/db?token=secret-value"
    failure = RuntimeError(marker)
    cursor = Mock()
    cursor.fetchone.side_effect = [(1,), ("auth_users", "token_blacklist_outstandingtoken")]
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    cache = Mock()
    cache.get.return_value = "pong"
    users = Mock()
    users.only.return_value.first.return_value = object()
    jwt = Mock(return_value="synthetic-jwt")
    cycles = Mock(return_value={"enforcement_ready": True})
    if failed_check == "database":
        connection.ensure_connection.side_effect = failure
        cursor.fetchone.side_effect = [("auth_users", "token_blacklist_outstandingtoken")]
    elif failed_check == "cache":
        cache.set.side_effect = failure
    elif failed_check == "auth_schema":
        connection.cursor.side_effect = [nullcontext(cursor), failure]
    elif failed_check == "jwt_mint":
        jwt.side_effect = failure
    else:
        cycles.side_effect = failure
    request = RequestFactory().get("/api/v1/health/ready")
    request.META["X_REQUEST_ID"] = "security-probe-test"
    with (
        patch("django.db.connection", connection),
        patch("django.core.cache.cache", cache),
        patch("apps.auth_user.models.User.objects", users),
        patch("ninja_jwt.tokens.AccessToken.for_user", jwt),
        patch("apps.support.assignment_readiness._conversation_cycle_checks", cycles),
        capture_logs() as logs,
    ):
        response = readiness_check(request)
    body = json.loads(response.content)
    if failed_check == "conversation_cycles":
        assert response.status_code == 200  # Informational probe retains existing semantics.
        assert body["assignment_runtime"]["conversation_cycles"] == {"enforcement_ready": False, "error": "unavailable"}
    else:
        assert response.status_code == 503
        assert body["checks"][failed_check] == "error"
    public_output = response.content.decode() + str(response.headers)
    for secret in (marker, "private.invalid", "password", "secret-value", "RuntimeError"):
        assert secret not in public_output
    assert any(
        event.get("check") == failed_check
        and event.get("error_type") == "RuntimeError"
        and event.get("request_id") == "security-probe-test"
        for event in logs
    )
    for secret in (marker, "password", "secret-value"):
        assert secret not in json.dumps(logs)
