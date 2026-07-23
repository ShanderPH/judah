"""Owner-token Redis locks used only as bounded orchestration optimizations."""

from __future__ import annotations

import secrets

import structlog
from django.conf import settings
from django.core.cache import cache
from redis import Redis

logger = structlog.get_logger(__name__)

_COMPARE_DELETE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class OwnedCacheLock:
    """A bounded lock that only its random-token owner may release."""

    def __init__(self, key: str, *, timeout: int) -> None:
        self.key = key
        self.timeout = timeout
        self.token = secrets.token_urlsafe(32)
        self.acquired = False

    def acquire(self) -> bool:
        """Acquire with an unguessable owner token."""
        if self._uses_redis_backend():
            self.acquired = bool(
                self._redis_client().set(
                    cache.make_key(self.key),
                    self.token,
                    nx=True,
                    ex=self.timeout,
                )
            )
        else:
            self.acquired = bool(cache.add(self.key, self.token, timeout=self.timeout))
        return self.acquired

    def release(self) -> bool:
        """Atomically compare-and-delete on Redis; otherwise rely on the TTL."""
        if not self.acquired:
            return False
        if self._uses_redis_backend():
            released = bool(
                self._redis_client().eval(
                    _COMPARE_DELETE,
                    1,
                    cache.make_key(self.key),
                    self.token,
                )
            )
        else:
            # Local-memory fallback is only used by isolated unit tests. Redis
            # is the production path and provides the atomic compare-delete.
            released = cache.get(self.key) == self.token
            if released:
                cache.delete(self.key)
        self.acquired = False
        return released

    @staticmethod
    def _uses_redis_backend() -> bool:
        """Return whether the configured default cache is Redis-backed."""
        backend = str(settings.CACHES["default"].get("BACKEND", ""))
        return "redis" in backend.lower()

    @staticmethod
    def _redis_client() -> Redis:
        """Create a dedicated synchronous redis-py client for lock scripts."""
        return Redis.from_url(str(settings.REDIS_URL), decode_responses=True)
