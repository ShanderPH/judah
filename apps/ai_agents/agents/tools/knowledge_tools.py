"""Agno tools for querying the InChurch knowledge base."""

from typing import Any

import structlog
from agno.tools import Toolkit

logger = structlog.get_logger(__name__)


class SearchKnowledgeBase(Toolkit):
    """Search the InChurch knowledge base using semantic (vector) search."""

    def __init__(self) -> None:
        super().__init__(name="search_knowledge_base")
        self.register(self.search)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Search the knowledge base for articles relevant to the query.

        Args:
            query: The user's question or search terms.
            top_k: Maximum number of results to return (default 5).

        Returns:
            List of dicts with article title, summary, and relevance score.
        """
        try:
            from apps.knowledge.services import semantic_search

            results = semantic_search(query=query, top_k=top_k)
            return [
                {
                    "article_id": r.article_id,
                    "title": r.title,
                    "summary": r.summary,
                    "score": r.score,
                }
                for r in results
            ]
        except Exception as exc:
            logger.error("knowledge_tool_search_failed", query=query, error=str(exc))
            return []
