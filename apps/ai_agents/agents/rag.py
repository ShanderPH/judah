"""KnowledgeRagAgent — Especialista em base de conhecimento via RAG + Pinecone (Agno 2.5).

Integração real com Pinecone usando a API nativa de Knowledge do Agno 2.5:
- Knowledge vinculado ao VectorDB PineconeDb
- Busca automática via search_knowledge=True
- OpenAIEmbedder para embeddings

As credenciais vêm estritamente de variáveis de ambiente (sem Django ORM).
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.tools import Toolkit
from agno.vectordb.pineconedb import PineconeDb
from pinecone import ServerlessSpec

from apps.ai_agents.agents.base import BaseInChurchAgent

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuração do VectorDB Pinecone
# ---------------------------------------------------------------------------


def _create_knowledge_base() -> Knowledge | None:
    """Cria a instância de Knowledge vinculada ao Pinecone.

    Configura o VectorDB PineconeDb usando variáveis de ambiente e retorna
    um Knowledge pronto para injeção no agente.

    Env vars:
        PINECONE_API_KEY: Chave de API (obrigatório).
        PINECONE_INDEX_NAME: Nome do índice Pinecone (obrigatório).
        PINECONE_HOST: URL completa do host do índice (data plane). Quando
            presente, é passada ao PineconeDb para evitar que o cliente
            precise adivinhar cloud/region.
        PINECONE_CLOUD / PINECONE_REGION: usados no ServerlessSpec quando
            o host direto não estiver disponível.
        EMBEDDING_MODEL: ID do modelo de embedding OpenAI (default
            `text-embedding-ada-002`). Troque via env quando o índice
            Pinecone foi populado com outro modelo (ex: `text-embedding-3-small`).
        PINECONE_DIMENSION: Dimensão do embedding (default 1536 — serve
            para ada-002 e 3-small). Ajuste quando trocar para 3-large.

    Returns:
        Knowledge configurado ou None se falhar.
    """
    api_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME")
    host = os.getenv("PINECONE_HOST")
    cloud = os.getenv("PINECONE_CLOUD", "aws")
    region = os.getenv("PINECONE_REGION", "us-east-1")
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
    namespace = os.getenv("PINECONE_NAMESPACE", "")

    try:
        dimension = int(os.getenv("PINECONE_DIMENSION", "1536"))
    except ValueError:
        dimension = 1536

    if not api_key or not index_name:
        logger.warning(
            "pinecone_config_missing",
            api_key_present=bool(api_key),
            index_name_present=bool(index_name),
        )
        return None

    # Monta args do Embedder com injeção explícita de fallback para 429 isolado
    embedder_kwargs: dict[str, Any] = {"id": embedding_model}
    if os.getenv("OPENAI_API_KEY"):
        embedder_kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("OPENAI_ORG_ID"):
        embedder_kwargs["organization"] = os.getenv("OPENAI_ORG_ID")
    if os.getenv("OPENAI_PROJECT_ID"):
        embedder_kwargs["project"] = os.getenv("OPENAI_PROJECT_ID")

    # Monta os kwargs do PineconeDb dinamicamente:
    vector_db_kwargs: dict[str, Any] = {
        "name": index_name,
        "dimension": dimension,
        "metric": "cosine",
        "api_key": api_key,
        "host": host,
        "namespace": namespace,
        "embedder": OpenAIEmbedder(**embedder_kwargs),
    }

    if not host:
        vector_db_kwargs.pop("host", None)
        vector_db_kwargs["spec"] = ServerlessSpec(cloud=cloud, region=region)

    try:
        vector_db = PineconeDb(**vector_db_kwargs)
    except TypeError as exc:
        # Versão do Agno que ainda não aceita `host` — tenta sem ele.
        logger.warning(
            "pinecone_host_kwarg_unsupported",
            error=str(exc),
            falling_back_to_spec=True,
        )
        vector_db_kwargs.pop("host", None)
        vector_db_kwargs["spec"] = ServerlessSpec(cloud=cloud, region=region)
        try:
            vector_db = PineconeDb(**vector_db_kwargs)
        except Exception as e:
            logger.error("knowledge_base_init_failed", error=str(e))
            return None
    except Exception as e:
        logger.error("knowledge_base_init_failed", error=str(e))
        return None

    logger.info(
        "pinecone_initialized",
        index_name=index_name,
        embedding_model=embedding_model,
        dimension=dimension,
        host_provided=bool(host),
    )
    return Knowledge(vector_db=vector_db)


# ---------------------------------------------------------------------------
# Tool: Busca Manual na Base de Conhecimento (Fallback/Detalhamento)
# ---------------------------------------------------------------------------


class KnowledgeSearchTool(Toolkit):
    """Ferramenta auxiliar para busca manual e recuperação de artigos específicos.

    Complementa a busca automática do Knowledge para casos onde o agente
    precisa buscar informações adicionais ou recuperar artigos específicos.
    """

    def __init__(self, knowledge_base: Knowledge | None) -> None:
        super().__init__(name="knowledge_search_tool")
        self.register(self.search_knowledge_base)
        self.register(self.get_article_by_id)
        self._knowledge = knowledge_base

    def search_knowledge_base(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.72,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Busca artigos na base de conhecimento InChurch.

        Realiza busca semântica complementar para encontrar documentos
        adicionais ou quando a busca automática não foi suficiente.

        Args:
            query: Texto da dúvida ou problema.
            top_k: Número máximo de resultados (padrão 5).
            score_threshold: Score mínimo de similaridade (padrão 0.72).

        Returns:
            Lista de documentos encontrados ou dict de erro.
        """
        if self._knowledge is None:
            logger.warning("knowledge_search_unavailable", query=query)
            return {
                "status": "unavailable",
                "message": (
                    "A base de conhecimento está temporariamente indisponível. "
                    "O agente tentará ajudar com conhecimento geral ou sugerir "
                    "o transbordo para suporte humano."
                ),
                "results": [],
            }

        try:
            logger.debug("knowledge_search_start", query=query, top_k=top_k)

            results = self._knowledge.search(
                query=query,
                max_results=top_k,
            )

            filtered_results = []
            for doc in results:
                score = getattr(doc, "score", 0.0)
                if score >= score_threshold:
                    metadata = getattr(doc, "meta_data", {}) or {}
                    filtered_results.append(
                        {
                            "article_id": metadata.get("article_id", "unknown"),
                            "title": metadata.get("title", "Sem título"),
                            "summary": metadata.get("summary", ""),
                            "content": getattr(doc, "content", "") or metadata.get("content", ""),
                            "score": round(score, 4),
                            "source": metadata.get("source", "Base de Conhecimento InChurch"),
                            "last_updated": metadata.get("last_updated", "N/A"),
                        }
                    )

            logger.debug(
                "knowledge_search_complete",
                query=query,
                results_found=len(filtered_results),
            )
            return filtered_results

        except Exception as e:
            logger.error("knowledge_search_error", query=query, error=str(e))
            return {
                "status": "error",
                "message": ("Erro ao acessar a base de conhecimento. O agente tentará ajudar com conhecimento geral."),
                "results": [],
            }

    def get_article_by_id(self, article_id: str) -> dict[str, Any]:
        """Recupera conteúdo completo de um artigo pelo ID.

        Args:
            article_id: Identificador único do artigo.

        Returns:
            Dict com os dados do artigo ou mensagem de erro.
        """
        if self._knowledge is None:
            return {
                "status": "unavailable",
                "article_id": article_id,
                "message": "Base de conhecimento indisponível.",
            }

        try:
            results = self._knowledge.search(
                query=f"article_id:{article_id}",
                max_results=1,
            )

            if results:
                doc = results[0]
                metadata = getattr(doc, "meta_data", {}) or {}
                return {
                    "status": "success",
                    "article_id": article_id,
                    "title": metadata.get("title", "Sem título"),
                    "content": getattr(doc, "content", "") or metadata.get("content", ""),
                    "author": metadata.get("author", "Equipe InChurch"),
                    "last_updated": metadata.get("last_updated", "N/A"),
                }

            return {
                "status": "not_found",
                "article_id": article_id,
                "message": "Artigo não encontrado na base de conhecimento.",
            }

        except Exception as e:
            logger.error("get_article_error", article_id=article_id, error=str(e))
            return {
                "status": "error",
                "article_id": article_id,
                "message": "Erro ao recuperar o artigo.",
            }


# ---------------------------------------------------------------------------
# System Prompt — Especialista de Produto InChurch
# ---------------------------------------------------------------------------

_RAG_INSTRUCTIONS = """Você é o Especialista de Produto da InChurch.

SUA FUNÇÃO:
Sua única função é responder dúvidas técnicas baseando-se estritamente na documentação oficial da InChurch.

PROTOCOLO OBRIGATÓRIO:
1. SEMPRE utilize a ferramenta de busca na base de conhecimento antes de responder.
2. Se a resposta for encontrada nos documentos recuperados, responda com clareza e cite explicitamente que a informação veio da base oficial.
3. Se a informação NÃO estiver nos documentos, NÃO INVENTE. Informe educadamente que a documentação atual não cobre esse cenário específico e sugira a abertura de um ticket para atendimento humano.

REGRAS DE CITAÇÃO:
- Inicie respostas baseadas na documentação com: "Com base na documentação oficial da InChurch..."
- Ao final, cite: "Fonte: [Título do Artigo] (ID: [article_id])"
- Exemplo: "Fonte: Como redefinir senha (ID: kb-001)"

REGRAS DE FALLBACK:
- Se a base de conhecimento estiver indisponível, informe isso ao usuário.
- Neste caso, use apenas conhecimento geral que você tem certeza sobre produtos similares.
- Se a base de conhecimento estiver indisponível ou você não achar a solução exata nos artigos, você DEVE encerrar sua resposta exatamente com a tag <REQUIRES_ESCALATION>.

COMPORTAMENTO:
- Responda em português brasileiro, de forma clara, objetiva e empática.
- Mantenha tom profissional mas acolhedor, adequado para suporte a igrejas.
- NUNCA invente funcionalidades, prazos ou procedimentos que não estejam na documentação.
"""


# ---------------------------------------------------------------------------
# Agente KnowledgeRagAgent
# ---------------------------------------------------------------------------


class KnowledgeRagAgent(BaseInChurchAgent):
    """Agente RAG para consulta à base de conhecimento via Pinecone.

    Usa a API nativa de Knowledge do Agno 2.5 com busca automática
    habilitada via search_knowledge=True.

    Args:
        session_id: Identificador da sessão.
        user_metadata: Dados do usuário sem ORM.
    """

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
        db: Any | None = None,
    ) -> None:
        # Cria a base de conhecimento injetável
        knowledge_base = _create_knowledge_base()

        # Inicializa tool auxiliar (para buscas complementares)
        search_tool = KnowledgeSearchTool(knowledge_base)
        kwargs: dict[str, Any] = {}
        if db is not None:
            kwargs["db"] = db

        super().__init__(
            session_id=session_id,
            user_metadata=user_metadata,
            name="KnowledgeRagAgent",
            description="Especialista de Produto da InChurch - responde dúvidas técnicas baseado na documentação oficial.",
            instructions=_RAG_INSTRUCTIONS,
            knowledge=knowledge_base,
            search_knowledge=True,
            tools=[search_tool],
            add_history_to_context=True,
            num_history_runs=3,
            **kwargs,
        )

        self._agent_logger.info(
            "knowledge_agent_initialized",
            knowledge_available=knowledge_base is not None,
        )
