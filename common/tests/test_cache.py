"""Tests for common.cache — key builder, cached decorator, prefix invalidation."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from common.cache import cached, invalidate_prefix, make_cache_key


class TestMakeCacheKey:
    def test_deterministic_for_same_args(self) -> None:
        assert make_cache_key("p", 1, 2, x="y") == make_cache_key("p", 1, 2, x="y")

    def test_different_args_produce_different_keys(self) -> None:
        assert make_cache_key("p", 1) != make_cache_key("p", 2)

    def test_different_prefix_produces_different_keys(self) -> None:
        assert make_cache_key("a", 1) != make_cache_key("b", 1)

    def test_kwarg_order_stable(self) -> None:
        assert make_cache_key("p", a=1, b=2) == make_cache_key("p", b=2, a=1)

    def test_key_shape(self) -> None:
        key = make_cache_key("prefix", 42)
        assert key.startswith("prefix:")
        # md5 digest — 32 hex chars.
        assert len(key.split(":", 1)[1]) == 32


class TestCachedDecorator:
    @pytest.fixture(autouse=True)
    def clear_cache(self) -> None:
        cache.clear()

    def test_function_result_is_cached(self) -> None:
        call_count = {"n": 0}

        @cached(timeout=60, prefix="test_cached_basic")
        def expensive(x: int) -> int:
            call_count["n"] += 1
            return x * 2

        assert expensive(5) == 10
        assert expensive(5) == 10
        assert call_count["n"] == 1  # second call served from cache

    def test_different_args_call_through(self) -> None:
        @cached(timeout=60, prefix="test_cached_args")
        def f(x: int) -> int:
            return x + 1

        assert f(1) == 2
        assert f(2) == 3

    def test_invalidate_clears_cached_value(self) -> None:
        call_count = {"n": 0}

        @cached(timeout=60, prefix="test_cached_invalidate")
        def f(x: int) -> int:
            call_count["n"] += 1
            return x * 3

        f(7)
        f.invalidate(7)
        f(7)
        assert call_count["n"] == 2

    def test_default_prefix_uses_qualname(self) -> None:
        call_count = {"n": 0}

        @cached(timeout=60)
        def g(x: int) -> int:
            call_count["n"] += 1
            return x

        g(1)
        g(1)
        assert call_count["n"] == 1


class TestInvalidatePrefix:
    def test_returns_zero_when_redis_unreachable(self) -> None:
        # When REDIS_URL is unreachable / test settings use locmem, the
        # function swallows the error and returns 0.
        result = invalidate_prefix("nonexistent-prefix-xyz")
        assert result == 0
