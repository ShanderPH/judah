"""Tests for the shared utility helpers (pure, no DB)."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from common.utils import (
    chunk_list,
    generate_uuid,
    is_valid_email,
    mask_secret,
    slugify,
    truncate,
    utcnow,
)


class TestGenerateUuid:
    def test_is_valid_uuid4(self) -> None:
        value = generate_uuid()
        parsed = UUID(value)
        assert parsed.version == 4

    def test_each_call_differs(self) -> None:
        assert generate_uuid() != generate_uuid()


class TestUtcNow:
    def test_returns_tz_aware_utc(self) -> None:
        now = utcnow()
        assert now.tzinfo is not None
        assert now.utcoffset().total_seconds() == 0
        assert now.tzinfo == UTC


class TestSlugify:
    def test_lowercases_and_dashes(self) -> None:
        assert slugify("Hello World") == "hello-world"

    def test_strips_special_chars(self) -> None:
        # Uses ASCII only to avoid encoding gotchas in test-runner output.
        assert slugify("  Hello, World!!!  ") == "hello-world"

    def test_collapses_multiple_spaces(self) -> None:
        assert slugify("a   b   c") == "a-b-c"

    def test_empty_string(self) -> None:
        assert slugify("") == ""


class TestTruncate:
    def test_short_string_not_truncated(self) -> None:
        assert truncate("hi", 10) == "hi"

    def test_long_string_truncated_with_default_suffix(self) -> None:
        result = truncate("abcdefghij", 6)
        assert result.endswith("...")
        assert len(result) == 6

    def test_custom_suffix(self) -> None:
        assert truncate("abcdefghij", 6, suffix="!") == "abcde!"


class TestChunkList:
    def test_even_split(self) -> None:
        assert chunk_list([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_uneven_split(self) -> None:
        assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_empty_list(self) -> None:
        assert chunk_list([], 3) == []


class TestMaskSecret:
    def test_masks_all_but_last_four(self) -> None:
        assert mask_secret("sk-abcdef1234") == "*********1234"

    def test_short_value_fully_masked(self) -> None:
        assert mask_secret("abc") == "***"


class TestIsValidEmail:
    def test_accepts_valid(self) -> None:
        assert is_valid_email("user@example.com") is True

    def test_rejects_missing_at(self) -> None:
        assert is_valid_email("userexample.com") is False

    def test_rejects_missing_tld(self) -> None:
        assert is_valid_email("user@example") is False

    def test_rejects_empty(self) -> None:
        assert is_valid_email("") is False
