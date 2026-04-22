"""BaseInChurchAgent — Agente fundacional do sistema multi-agente Salomão.

Decisão arquitetural: herdar de agno.agent.Agent (em vez de composição) permite
que o supervisor reutilize toda a infra do Agno (tool-calling, streaming, tracing,
session management) sem reimplementar nada. O padrão adotado é um `__init_subclass__`
mínimo que injeta Redis, fallback e logging antes de repassar ao `Agent.__init__`.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from agno.agent import Agent
from agno.db.redis import RedisDb
from agno.models.fallback import FallbackConfig
from agno.models.openai import OpenAIChat
from django.conf import settings

# ---------------------------------------------------------------------------
# Configuração de modelos via variáveis de ambiente.
# - DEFAULT_MODEL: modelo principal para raciocínio complexo (supervisor, RAG).
# - DEFAULT_MINI_MODEL: modelo rápido/barato para tarefas de alta frequência
#   e baixo custo cognitivo (triagem). Também usado como fallback.
# Mantê-los como módulo-level constants permite trocar o provedor/modelo
# em um só lugar sem tocar no corpo dos agentes.
# ---------------------------------------------------------------------------
DEFAULT_MODEL_ID: str = os.getenv("DEFAULT_MODEL", "gpt-4o")
DEFAULT_MINI_MODEL_ID: str = os.getenv("DEFAULT_MINI_MODEL", "gpt-4o-mini")


def _get_openai_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    org = os.getenv("OPENAI_ORG_ID")
    if org:
        kwargs["organization"] = org
    proj = os.getenv("OPENAI_PROJECT_ID")
    if proj:
        kwargs["project"] = proj
    return kwargs


def build_primary_model() -> OpenAIChat:
    """Modelo primário (raciocínio complexo)."""
    return OpenAIChat(id=DEFAULT_MODEL_ID, **_get_openai_kwargs())


def build_mini_model() -> OpenAIChat:
    """Modelo compacto para triagem e tarefas de alta frequência."""
    return OpenAIChat(id=DEFAULT_MINI_MODEL_ID, **_get_openai_kwargs())


def _build_redis_db(session_id: str) -> RedisDb:
    """Instancia o RedisDb para persistência de sessão.

    Usa a variável REDIS_URL do settings do Django para que a configuração
    seja centralizada e não duplicada nos agents.
    """
    redis_url: str = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    return RedisDb(
        db_url=redis_url,
        # Prefixo por session_id garante isolamento total entre conversas.
        db_prefix=f"inchurch:agent:{session_id}",
    )


def _build_fallback_config() -> FallbackConfig:
    """Política de fallback global: Claude Sonnet em caso de erro ou rate-limit.

    Decisão: manter dois níveis de fallback (erro genérico + rate-limit) com o
    mesmo modelo alternativo simplifica o monitoramento. Se o fallback também
    falhar, a exceção sobe normalmente para o handler do Django.
    """
    fallback_model = build_mini_model()
    return FallbackConfig(
        on_error=[fallback_model],
        on_rate_limit=[fallback_model],
    )


class BaseInChurchAgent(Agent):
    """Agente base para todos os agentes InChurch.

    Responsabilidades:
    - Injetar o modelo primário (GPT-4o) com fallback automático para GPT-4o-mini.
    - Conectar o armazenamento de sessão ao Redis usando o `session_id` do usuário Django.
    - Expor `user_metadata` para que sub-agentes possam personalizar respostas
      sem acessar o ORM diretamente (desacoplamento crítico em agentes assíncronos).
    - Configurar logging estruturado via structlog.

    Args:
        session_id: Identificador único da sessão, tipicamente derivado do ID do
            usuário Django autenticado (ex: `f"user-{request.user.pk}"`).
        user_metadata: Dicionário com dados do usuário (nome, e-mail, church_id,
            hubspot_contact_id, etc.) passado no momento da instanciação —
            nunca buscado via ORM dentro do agente.
        **kwargs: Parâmetros extras repassados a `agno.agent.Agent`, permitindo
            que sub-classes sobrescrevam model, instructions, tools, etc.
    """

    user_metadata: dict[str, Any]
    _agent_logger: structlog.stdlib.BoundLogger

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        # Guarda metadados antes do super().__init__ para que instruções
        # dinâmicas (que referenciam user_metadata) possam ser construídas
        # nas sub-classes antes de chamar super().
        self.user_metadata = user_metadata
        self._agent_logger = structlog.get_logger(self.__class__.__name__).bind(
            session_id=session_id,
            user_id=user_metadata.get("user_id"),
            church_id=user_metadata.get("church_id"),
        )

        # Injeta padrões que podem ser sobrescritos via kwargs.
        kwargs.setdefault("model", build_primary_model())
        kwargs.setdefault("fallback_config", _build_fallback_config())
        kwargs.setdefault("db", _build_redis_db(session_id))

        # Habilita histórico de sessão para contexto contínuo de conversa.
        kwargs.setdefault("add_history_to_context", True)
        kwargs.setdefault("num_history_runs", 5)
        kwargs.setdefault("markdown", True)
        kwargs.setdefault("debug_mode", getattr(settings, "DEBUG", False))

        super().__init__(session_id=session_id, **kwargs)

        self._agent_logger.info(
            "agent_initialized",
            agent_name=self.name,
            model_id=self.model.id if self.model else "unknown",  # type: ignore[union-attr]
        )
