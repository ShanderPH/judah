"""Tests for knowledge services with provider calls mocked."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.knowledge.models import Article
from apps.knowledge.services import get_article_by_slug, list_published_articles, semantic_search
from common.exceptions import NotFoundError


def _published_status():
    return patch.object(Article, "Status", SimpleNamespace(PUBLISHED="PUBLISHED"), create=True)


def test_article_lookup_and_listing() -> None:
    article = SimpleNamespace()
    get_qs = Mock()
    get_qs.get.return_value = article
    list_qs = Mock()
    selected_qs = Mock()
    filtered_qs = Mock()
    filtered_qs.order_by.return_value = [article]
    list_qs.select_related.return_value = selected_qs
    selected_qs.filter.return_value = filtered_qs

    with (
        _published_status(),
        patch("apps.knowledge.services.Article.objects.select_related", return_value=get_qs),
        patch("apps.knowledge.services.Article.objects.filter", return_value=list_qs),
    ):
        assert get_article_by_slug("login") is article
        assert list_published_articles("financeiro") == [article]

    get_qs.get.assert_called_once_with(slug="login", status="PUBLISHED")
    selected_qs.filter.assert_called_once_with(category__slug="financeiro")


def test_article_lookup_maps_not_found() -> None:
    queryset = Mock()
    queryset.get.side_effect = Article.DoesNotExist
    with (
        _published_status(),
        patch("apps.knowledge.services.Article.objects.select_related", return_value=queryset),
        pytest.raises(NotFoundError),
    ):
        get_article_by_slug("missing")


def test_semantic_search_returns_known_articles_and_skips_unknown() -> None:
    pinecone = Mock()
    pinecone.search.return_value = [
        {"score": 0.95, "metadata": {"article_id": "1"}},
        {"score": 0.80, "metadata": {"article_id": "999"}},
        {"score": 0.70, "metadata": {}},
    ]
    article = SimpleNamespace(pk=1, title="Login", summary="Como entrar")
    with (
        patch("apps.integrations.pinecone_client.client.get_pinecone_client", return_value=pinecone),
        patch("apps.knowledge.services.Article.objects.filter", return_value=[article]),
    ):
        results = semantic_search("login", top_k=3)

    assert len(results) == 1
    assert results[0].article_id == 1
    assert results[0].score == 0.95


def test_semantic_search_returns_empty_on_provider_failure() -> None:
    with patch(
        "apps.integrations.pinecone_client.client.get_pinecone_client",
        side_effect=RuntimeError("offline"),
    ):
        assert semantic_search("login") == []
