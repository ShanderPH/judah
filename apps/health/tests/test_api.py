"""Tests for liveness and readiness probes."""

from contextlib import nullcontext
from unittest.mock import Mock, patch

from apps.health.api import health_check, readiness_check


def test_liveness_returns_process_metadata() -> None:
    response = health_check(None)
    assert response["status"] == "alive"
    assert response["version"] == "1.0.0"
    assert response["timestamp"]


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
    assert b"db down" in response.content
    assert b"cache down" in response.content
    assert b"jwt broken" in response.content
