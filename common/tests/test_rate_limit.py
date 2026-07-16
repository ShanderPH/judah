"""Tests for API rate-limit middleware."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from common.rate_limit import RateLimitMiddleware, _get_client_identifier


def test_client_identifier_prefers_user_then_forwarded_ip() -> None:
    request = SimpleNamespace(auth=SimpleNamespace(pk=7), META={})
    assert _get_client_identifier(request) == "user:7"
    request = SimpleNamespace(auth=None, META={"HTTP_X_FORWARDED_FOR": "1.2.3.4, 5.6.7.8"})
    assert _get_client_identifier(request) == "ip:1.2.3.4"
    request = SimpleNamespace(META={"REMOTE_ADDR": "9.9.9.9"})
    assert _get_client_identifier(request) == "ip:9.9.9.9"


@override_settings(RATE_LIMIT_OVERRIDES={"/api/v1/ai/": (2, 30)})
def test_rate_limit_non_api_override_headers_and_limit() -> None:
    get_response = Mock(return_value=HttpResponse("ok"))
    middleware = RateLimitMiddleware(get_response)
    factory = RequestFactory()

    assert middleware(factory.get("/health/")).status_code == 200
    assert middleware._get_limits("/api/v1/ai/chat") == (2, 30)
    assert middleware._get_limits("/api/v1/other") == (100, 60)

    request = factory.get("/api/v1/ai/chat", REMOTE_ADDR="1.2.3.4")
    with patch("common.rate_limit.cache") as cache:
        cache.get.side_effect = [0, None]
        response = middleware(request)
    assert response["X-RateLimit-Limit"] == "2"
    assert response["X-RateLimit-Remaining"] == "1"
    assert cache.set.call_count == 2

    with patch("common.rate_limit.cache") as cache:
        cache.get.return_value = 2
        response = middleware(request)
    assert response.status_code == 429
    assert response["Retry-After"] == "30"


def test_rate_limit_fail_open_increment_race_and_counter_failure() -> None:
    middleware = RateLimitMiddleware(lambda request: HttpResponse("ok"))
    request = RequestFactory().get("/api/v1/test", REMOTE_ADDR="1.2.3.4")

    with patch("common.rate_limit.cache.get", side_effect=RuntimeError("cache down")):
        assert middleware(request).status_code == 200

    with patch("common.rate_limit.cache") as cache:
        cache.get.side_effect = [1, 1]
        cache.incr.side_effect = ValueError("expired")
        response = middleware(request)
    assert response.status_code == 200
    assert cache.set.call_count == 2

    with patch("common.rate_limit.cache") as cache:
        cache.get.side_effect = [0, None]
        cache.set.side_effect = RuntimeError("write failed")
        assert middleware(request).status_code == 200
