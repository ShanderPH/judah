"""Tests for RAG knowledge configuration and search tool behavior."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.ai_agents.agents import rag
from apps.ai_agents.agents.rag import KnowledgeSearchTool, ScoredPineconeDb


def test_create_knowledge_base_missing_config(monkeypatch) -> None:
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    monkeypatch.delenv("PINECONE_INDEX_NAME", raising=False)
    assert rag._create_knowledge_base() is None


def test_create_knowledge_base_host_and_serverless(monkeypatch) -> None:
    monkeypatch.setenv("PINECONE_API_KEY", "key")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "index")
    monkeypatch.setenv("PINECONE_HOST", "https://host")
    monkeypatch.setenv("PINECONE_DIMENSION", "invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "openai")
    monkeypatch.setenv("OPENAI_ORG_ID", "org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "project")
    vector = object()
    knowledge = object()
    with (
        patch("apps.ai_agents.agents.rag.OpenAIEmbedder", return_value="embedder") as embedder,
        patch("apps.ai_agents.agents.rag.ServerlessSpec", return_value="spec"),
        patch("apps.ai_agents.agents.rag.ScoredPineconeDb", return_value=vector) as pinecone,
        patch("apps.ai_agents.agents.rag.Knowledge", return_value=knowledge),
    ):
        assert rag._create_knowledge_base() is knowledge
    assert pinecone.call_args.kwargs["dimension"] == 1536
    assert pinecone.call_args.kwargs["host"] == "https://host"
    assert pinecone.call_args.kwargs["spec"] == "spec"
    assert embedder.call_args.kwargs["id"] == "text-embedding-3-small"
    assert embedder.call_args.kwargs["organization"] == "org"

    monkeypatch.delenv("PINECONE_HOST")
    with (
        patch("apps.ai_agents.agents.rag.OpenAIEmbedder", return_value="embedder"),
        patch("apps.ai_agents.agents.rag.ServerlessSpec", return_value="spec"),
        patch("apps.ai_agents.agents.rag.ScoredPineconeDb", return_value=vector) as pinecone,
        patch("apps.ai_agents.agents.rag.Knowledge", return_value=knowledge),
    ):
        assert rag._create_knowledge_base() is knowledge
    assert "host" not in pinecone.call_args.kwargs
    assert pinecone.call_args.kwargs["spec"] == "spec"


def test_create_knowledge_base_fallback_and_failures(monkeypatch) -> None:
    monkeypatch.setenv("PINECONE_API_KEY", "key")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "index")
    monkeypatch.setenv("PINECONE_HOST", "https://host")
    vector = object()
    with (
        patch("apps.ai_agents.agents.rag.OpenAIEmbedder", return_value="embedder"),
        patch("apps.ai_agents.agents.rag.ScoredPineconeDb", side_effect=[TypeError("host"), vector]) as pinecone,
        patch("apps.ai_agents.agents.rag.Knowledge", return_value="knowledge"),
    ):
        assert rag._create_knowledge_base() == "knowledge"
    assert pinecone.call_count == 2

    with (
        patch("apps.ai_agents.agents.rag.OpenAIEmbedder", return_value="embedder"),
        patch(
            "apps.ai_agents.agents.rag.ScoredPineconeDb",
            side_effect=[TypeError("host"), RuntimeError("offline")],
        ),
    ):
        assert rag._create_knowledge_base() is None

    with (
        patch("apps.ai_agents.agents.rag.OpenAIEmbedder", return_value="embedder"),
        patch("apps.ai_agents.agents.rag.ScoredPineconeDb", side_effect=RuntimeError("offline")),
    ):
        assert rag._create_knowledge_base() is None


def test_knowledge_search_unavailable_success_and_error() -> None:
    unavailable = KnowledgeSearchTool(None)
    assert unavailable.search_knowledge_base("login")["status"] == "unavailable"
    assert unavailable.get_article_by_id("1")["status"] == "unavailable"

    knowledge = Mock()
    knowledge.search.return_value = [
        SimpleNamespace(
            score=0.9,
            content="Conteúdo",
            meta_data={"article_id": "1", "title": "Login", "summary": "Resumo"},
        ),
        SimpleNamespace(score=0.5, content="Ignorado", meta_data={}),
    ]
    tool = KnowledgeSearchTool(knowledge)
    results = tool.search_knowledge_base("login", top_k=2, score_threshold=0.7)
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["score"] == 0.9
    assert tool.get_article_by_id("1")["status"] == "success"

    knowledge.search.return_value = []
    assert tool.get_article_by_id("missing")["status"] == "not_found"

    knowledge.search.side_effect = RuntimeError("offline")
    assert tool.search_knowledge_base("login")["status"] == "error"
    assert tool.get_article_by_id("1")["status"] == "error"


def test_scored_pinecone_search_preserves_provider_score() -> None:
    vector_db = ScoredPineconeDb.__new__(ScoredPineconeDb)
    vector_db.embedder = Mock()
    vector_db.embedder.get_embedding.return_value = [0.1, 0.2]
    vector_db._index = Mock()
    vector_db._index.query.return_value = SimpleNamespace(
        matches=[
            SimpleNamespace(
                id="chunk-1",
                score=0.706658,
                values=None,
                metadata={
                    "text": "Acesse a visualiza��o:Ingressos",
                    "title": '<span class="highlight">Eventos</span>',
                    "article_id": 123.0,
                },
            )
        ]
    )
    vector_db.namespace = ""
    vector_db.use_hybrid_search = False
    vector_db.reranker = None

    documents = vector_db.search("como criar cupom de desconto")

    assert documents[0].reranking_score == 0.706658
    assert documents[0].meta_data["_pinecone_score"] == 0.706658
    assert documents[0].content == "Acesse a visualizao: Ingressos"
    assert documents[0].meta_data["title"] == "Eventos"


def test_knowledge_search_accepts_realistic_score_and_cleans_hubspot_title() -> None:
    knowledge = Mock()
    knowledge.search.return_value = [
        SimpleNamespace(
            id="chunk-1",
            reranking_score=0.706658,
            content="Abra o evento e acesse Ingressos.",
            meta_data={
                "article_id": 190785094175.0,
                "title": '<span class="highlight">Eventos</span> | Como criar um cupom',
                "url": "https://portal.inchurch.com.br/artigo",
            },
        )
    ]

    results = KnowledgeSearchTool(knowledge).search_knowledge_base("como criar cupom de desconto")

    assert isinstance(results, list)
    assert results[0]["article_id"] == 190785094175
    assert results[0]["title"] == "Eventos | Como criar um cupom"
    assert results[0]["score"] == 0.7067


def test_rag_agent_wires_knowledge_and_optional_db() -> None:
    captured = {}

    def fake_base_init(instance, session_id, user_metadata, **kwargs):
        captured.update(kwargs)
        instance._agent_logger = Mock()

    with (
        patch("apps.ai_agents.agents.rag._create_knowledge_base", return_value="knowledge"),
        patch("apps.ai_agents.agents.rag.BaseInChurchAgent.__init__", new=fake_base_init),
    ):
        rag.KnowledgeRagAgent("session", {"user_id": 1}, db="db")

    assert captured["knowledge"] == "knowledge"
    assert captured["db"] == "db"
    assert captured["search_knowledge"] is True
