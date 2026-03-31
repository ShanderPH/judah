"""Pinecone vector store client for JUDAH."""

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_pinecone_index = None


class PineconeClient:
    """Wrapper around the Pinecone index for vector operations."""

    def __init__(self, index: Any) -> None:
        self._index = index

    def upsert(self, vectors: list[dict[str, Any]], namespace: str = "") -> dict[str, Any]:
        """Upsert vectors into the Pinecone index.

        Args:
            vectors: List of dicts with id, values, and optional metadata.
            namespace: Optional namespace for partitioning.

        Returns:
            Upsert response dict.
        """
        try:
            response = self._index.upsert(vectors=vectors, namespace=namespace)
            logger.info("pinecone_upsert", count=len(vectors), namespace=namespace)
            return response
        except Exception as exc:
            logger.error("pinecone_upsert_failed", error=str(exc))
            raise

    def search(self, query: str, top_k: int = 5, namespace: str = "", filter: dict | None = None) -> list[dict[str, Any]]:
        """Perform a semantic search by embedding the query and querying the index.

        Args:
            query: Natural language query to embed and search.
            top_k: Maximum number of results.
            namespace: Optional namespace filter.
            filter: Optional metadata filter dict.

        Returns:
            List of match dicts with id, score, and metadata.
        """
        from openai import OpenAI

        from django.conf import settings

        embedding_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        embedding_response = embedding_client.embeddings.create(
            input=query,
            model="text-embedding-3-small",
        )
        query_vector = embedding_response.data[0].embedding

        try:
            response = self._index.query(
                vector=query_vector,
                top_k=top_k,
                namespace=namespace,
                filter=filter,
                include_metadata=True,
            )
            return [
                {"id": m["id"], "score": m["score"], "metadata": m.get("metadata", {})}
                for m in response.get("matches", [])
            ]
        except Exception as exc:
            logger.error("pinecone_search_failed", query=query[:50], error=str(exc))
            raise

    def delete(self, ids: list[str], namespace: str = "") -> None:
        """Delete vectors by ID from the index.

        Args:
            ids: List of vector IDs to delete.
            namespace: Optional namespace.
        """
        self._index.delete(ids=ids, namespace=namespace)
        logger.info("pinecone_delete", count=len(ids), namespace=namespace)


def get_pinecone_client() -> PineconeClient:
    """Return a configured PineconeClient (lazy-initialized singleton).

    Returns:
        PineconeClient instance wrapping the configured index.
    """
    global _pinecone_index
    if _pinecone_index is None:
        from pinecone import Pinecone

        from django.conf import settings

        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        _pinecone_index = pc.Index(settings.PINECONE_INDEX_NAME)
        logger.info("pinecone_client_initialized", index=settings.PINECONE_INDEX_NAME)

    return PineconeClient(_pinecone_index)
