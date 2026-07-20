"""Owner-token Redis locks used only as bounded orchestration optimizations."""

from __future__ import annotations

import secrets

import structlog
from django.core.cache import cache

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
        self.acquired = bool(cache.add(self.key, self.token, timeout=self.timeout))
        return self.acquired

    def release(self) -> bool:
        """Atomically compare-and-delete on Redis; otherwise rely on the TTL."""
        if not self.acquired:
            return False
        cache_client = getattr(cache, "client", None)
        get_client = getattr(cache_client, "get_client", None)
        if get_client is None:
            logger.warning("owned_cache_lock_release_deferred_to_ttl", lock_key=self.key)
            return False
        redis = get_client(write=True)
        released = bool(redis.eval(_COMPARE_DELETE, 1, cache.make_key(self.key), self.token))
        self.acquired = False
        return released
