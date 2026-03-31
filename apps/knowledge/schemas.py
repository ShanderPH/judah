"""Pydantic v2 schemas for knowledge endpoints."""

from ninja import Schema


class CategoryResponse(Schema):
    """Public category representation."""

    id: int
    name: str
    slug: str
    description: str

    class Config:
        from_attributes = True


class ArticleListResponse(Schema):
    """Minimal article representation for list endpoints."""

    id: int
    title: str
    slug: str
    summary: str
    status: str
    view_count: int

    class Config:
        from_attributes = True


class ArticleResponse(Schema):
    """Full article representation."""

    id: int
    title: str
    slug: str
    content: str
    summary: str
    status: str
    view_count: int
    helpful_count: int
    not_helpful_count: int

    class Config:
        from_attributes = True


class SearchRequest(Schema):
    """Payload for semantic search."""

    query: str
    top_k: int = 5
    category_slug: str | None = None


class SearchResultItem(Schema):
    """A single search result."""

    article_id: int
    title: str
    summary: str
    score: float
    url: str | None = None
