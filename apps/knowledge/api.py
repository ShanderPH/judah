"""Django Ninja API endpoints for knowledge base."""

from ninja import Router

from apps.knowledge.models import Article
from apps.knowledge.schemas import ArticleListResponse, ArticleResponse, SearchRequest, SearchResultItem
from apps.knowledge.services import get_article_by_slug, list_published_articles, semantic_search
from common.pagination import StandardPagination, paginate

router = Router()


@router.get("/articles/", response=list[ArticleListResponse], summary="List published articles")
@paginate(StandardPagination)
def list_articles(request, category: str | None = None) -> list[Article]:
    """Return paginated published articles, optionally filtered by category slug."""
    return list_published_articles(category_slug=category)


@router.get("/articles/{slug}", response=ArticleResponse, summary="Get article by slug")
def get_article(request, slug: str) -> Article:
    """Return a single published article."""
    return get_article_by_slug(slug)


@router.post("/search/", response=list[SearchResultItem], auth=None, summary="Semantic search")
def search(request, payload: SearchRequest) -> list[SearchResultItem]:
    """Perform semantic (vector) search over the knowledge base."""
    return semantic_search(
        query=payload.query,
        top_k=payload.top_k,
        category_slug=payload.category_slug,
    )
