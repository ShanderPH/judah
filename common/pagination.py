"""Standard pagination classes for JUDAH API."""

from typing import TypeVar

from ninja import Schema
from ninja.pagination import CursorPagination, LimitOffsetPagination, paginate

T = TypeVar("T")


class PagedResponse[T](Schema):
    """Generic paged response envelope."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[T]


class CursorPagedResponse[T](Schema):
    """Cursor-based paged response envelope."""

    next: str | None = None
    previous: str | None = None
    results: list[T]


class StandardPagination(LimitOffsetPagination):
    """Default offset-based pagination with configurable page size."""

    class Input(LimitOffsetPagination.Input):
        limit: int = 20

    max_limit = 100


class StandardCursorPagination(CursorPagination):
    """Default cursor-based pagination — recommended for large datasets."""

    page_size = 20
    max_page_size = 100
    ordering = "-created_at"


__all__ = [
    "CursorPagedResponse",
    "PagedResponse",
    "StandardCursorPagination",
    "StandardPagination",
    "paginate",
]
