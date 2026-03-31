"""Redis cache decorators and helpers for JUDAH."""

import functools
import hashlib
import json
from typing import TYPE_CHECKING, Any

import structlog
from django.core.cache import cache

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


def make_cache_key(prefix: str, *args: Any, **kwargs: Any) -> str:
    """Generate a deterministic cache key from a prefix and arguments."""
    raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    digest = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
    return f"{prefix}:{digest}"


def cached(timeout: int = 300, prefix: str = "") -> Callable:
    """Decorator to cache the return value of a function in Redis.

    Args:
        timeout: Cache TTL in seconds (default 5 minutes).
        prefix: Cache key prefix; defaults to the function's qualified name.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key_prefix = prefix or f"{func.__module__}.{func.__qualname__}"
            cache_key = make_cache_key(key_prefix, *args, **kwargs)
            result = cache.get(cache_key)
            if result is not None:
                logger.debug("cache_hit", key=cache_key)
                return result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            logger.debug("cache_set", key=cache_key, timeout=timeout)
            return result

        def invalidate(*args: Any, **kwargs: Any) -> None:
            """Invalidate the cached value for the given arguments."""
            key_prefix = prefix or f"{func.__module__}.{func.__qualname__}"
            cache_key = make_cache_key(key_prefix, *args, **kwargs)
            cache.delete(cache_key)
            logger.debug("cache_invalidated", key=cache_key)

        wrapper.invalidate = invalidate  # type: ignore[attr-defined]
        return wrapper

    return decorator


def invalidate_prefix(prefix: str) -> int:
    """Delete all cache keys matching a prefix pattern.

    Returns the number of keys deleted.
    """
    pattern = f"{prefix}:*"
    try:
        from django_redis import get_redis_connection

        conn = get_redis_connection("default")
        keys = conn.keys(pattern)
        if keys:
            return conn.delete(*keys)
    except Exception:
        logger.warning("cache_prefix_invalidation_failed", prefix=prefix)
    return 0
