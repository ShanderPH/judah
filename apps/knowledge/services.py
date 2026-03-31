"""Business logic for knowledge base — CRUD and semantic search."""

import structlog

from apps.knowledge.models import Article, Category
from apps.knowledge.schemas import SearchResultItem
from common.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


def get_article_by_slug(slug: str) -> Article:
    """Fetch a published article by slug.

    Raises:
        NotFoundError: If no published article with that slug exists.
    """
    try:
        return Article.objects.select_related("category").get(slug=slug, status=Article.Status.PUBLISHED)
    except Article.DoesNotExist:
        raise NotFoundError(f"Article '{slug}' not found.")


def list_published_articles(category_slug: str | None = None) -> list[Article]:
    """Return published articles, optionally filtered by category."""
    qs = Article.objects.filter(status=Article.Status.PUBLISHED).select_related("category")
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    return list(qs.order_by("-updated_at"))


def semantic_search(query: str, top_k: int = 5, category_slug: str | None = None) -> list[SearchResultItem]:
    """Perform semantic search over article embeddings via Pinecone.

    Args:
        query: Natural-language search query.
        top_k: Maximum number of results to return.
        category_slug: Optional category filter.

    Returns:
        List of SearchResultItem ordered by relevance score.
    """
    from apps.integrations.pinecone_client.client import get_pinecone_client
    from apps.integrations.supabase_client.client import get_supabase_client

    try:
        pinecone = get_pinecone_client()
        results = pinecone.search(query=query, top_k=top_k)
    except Exception as exc:
        logger.error("semantic_search_failed", query=query, error=str(exc))
        return []

    article_ids = [int(r["metadata"]["article_id"]) for r in results if "article_id" in r.get("metadata", {})]
    articles = {a.pk: a for a in Article.objects.filter(pk__in=article_ids)}

    items: list[SearchResultItem] = []
    for result in results:
        meta = result.get("metadata", {})
        article_id = int(meta.get("article_id", 0))
        article = articles.get(article_id)
        if article:
            items.append(
                SearchResultItem(
                    article_id=article.pk,
                    title=article.title,
                    summary=article.summary,
                    score=result.get("score", 0.0),
                )
            )
    return items
