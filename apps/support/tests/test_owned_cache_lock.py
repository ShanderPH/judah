"""Redis-backed owner-token lock integration tests."""

from __future__ import annotations

import os
import secrets

import pytest
from django.core.cache import cache
from django.test import override_settings
from redis import Redis

from apps.support.owned_cache_lock import OwnedCacheLock

REDIS_TEST_URL = os.environ.get("JUDAH_TEST_REDIS_URL", "")
pytestmark = pytest.mark.skipif(not REDIS_TEST_URL, reason="JUDAH_TEST_REDIS_URL is required")


@pytest.fixture(autouse=True)
def redis_cache_settings():
    """Route only this module to the explicitly supplied disposable Redis."""
    with override_settings(
        REDIS_URL=REDIS_TEST_URL,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": REDIS_TEST_URL,
            }
        },
    ):
        cache.clear()
        yield
        cache.clear()


def test_release_immediately_deletes_only_owned_token() -> None:
    lock = OwnedCacheLock(f"test-lock:{secrets.token_hex(8)}", timeout=30)

    assert lock.acquire() is True
    assert lock.release() is True
    assert cache.get(lock.key) is None


def test_foreign_token_is_never_deleted() -> None:
    lock = OwnedCacheLock(f"test-lock:{secrets.token_hex(8)}", timeout=30)
    assert lock.acquire() is True
    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    redis_key = cache.make_key(lock.key)
    client.set(redis_key, "foreign-owner", ex=30)

    assert lock.release() is False
    assert client.get(redis_key) == "foreign-owner"


def test_lock_has_bounded_crash_recovery_ttl() -> None:
    lock = OwnedCacheLock(f"test-lock:{secrets.token_hex(8)}", timeout=5)
    assert lock.acquire() is True
    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)

    ttl = client.ttl(cache.make_key(lock.key))

    assert 0 < ttl <= 5
