"""SalomaoSupervisorAgent — Maestro do sistema multi-agente Salomão.

Decisão arquitetural: o Supervisor é implementado como um `agno.team.Team`
(modo `coordinate`) em vez de um agente simples. No modo `coordinate`, o
Team age como um "maestro LLM" que decide quais membros acionar, em que
ordem, e como sintetizar as respostas parciais em uma resposta final coesa.

O `SalomaoSupervisorAgent` é uma classe wrapper que:
1. Instancia os sub-agentes passando o mesmo `session_id` e `user_metadata`.
2. Monta o `Team` com `TeamMode.coordinate`.
3. Expõe o método `run_pipeline()` com saída tipada para a API Django Ninja.

Por que não herdar de `BaseInChurchAgent` diretamente?
`agno.team.Team` não herda de `agno.agent.Agent` — são classes separadas.
O wrapper garante que a interface pública permaneça consistente sem violar
a hierarquia de tipos do Agno.
"""

from __future__ import annotations

from typing import Any

import structlog
from agno.team import Team
from agno.team.team import TeamMode
from pydantic import BaseModel

from apps.ai_agents.agents.action import HelpdeskActionAgent, MCPServerConfig
from apps.ai_agents.agents.base import (
    BaseInChurchAgent,
    _build_fallback_config,
    _build_redis_db,
    build_primary_model,
)
from apps.ai_agents.agents.rag import KnowledgeRagAgent
from apps.ai_agents.agents.triage import HeimdallTriageAgent

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Schema de saída para Django Ninja
# ---------------------------------------------------------------------------


class SalomaoResponse(BaseModel):
    """Resposta final formatada para consumo pela API Django Ninja.

    Estrutura consistente que abstrai os detalhes internos do Team Agno
    e garante serialização previsível pelo Ninja.
    """

    session_id: str
    message: str
    sources: list[dict[str, Any]]
    requires_human_handoff: bool
    handoff_reason: str | None
    agent_trace: list[str]
    tokens_used: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_name: str = ""
    latency_ms: int


# ---------------------------------------------------------------------------
# Agente Supervisor Principal
# ---------------------------------------------------------------------------

_SUPERVISOR_INSTRUCTIONS = [
    "Você é Salomão, o assistente virtual de suporte da InChurch.",
    "FLUXO OBRIGATÓRIO: SEMPRE acione o Heimdall PRIMEIRO para obter a "
    "classificação estruturada da mensagem (campos rota, prioridade, tags, "
    "dados_faltantes, sentimento).",
    "Depois, faça o HAND-OFF para o agente correto usando o campo `rota` do "
    "Heimdall — não decida sozinho e não responda diretamente ao usuário "
    "antes da delegação:",
    "  • rota ∈ {DUVIDAS_PLATAFORMA, ATENDIMENTO_IA} → delegar ao "
    "KnowledgeRagAgent para consulta à base de conhecimento (Pinecone).",
    "  • rota ∈ {BOLETO, MEIOS_DE_PAGAMENTO, FINANCEIRO, SUPORTE_TECNICO_N1, "
    "EVENTOS, CUSTOMER_SUCCESS} → delegar ao HelpdeskAction para ações no "
    "HubSpot, Jira, n8n e Central de Ajuda (criar/atualizar ticket, "
    "registrar issue, disparar workflow).",
    "  • rota == ESCALAR_IMEDIATAMENTE → NÃO tente resolver. Sinalize "
    "transbordo humano imediato incluindo 'requires_human_handoff: true' e "
    "'transbordo para atendimento humano' na resposta final.",
    "Se prioridade == CRITICA, destaque a urgência na resposta final e "
    "sinalize transbordo humano mesmo que a rota não seja ESCALAR_IMEDIATAMENTE.",
    "Repasse tags, dados_faltantes e sentimento como contexto estruturado ao "
    "agente delegado — não descarte o output do Heimdall.",
    "Sintetize a resposta final em português brasileiro, cordial e objetivo "
    "(máx 3 parágrafos). Cite as fontes quando o KnowledgeRagAgent as retornar.",
]


class SalomaoSupervisorAgent:
    """Supervisor do sistema multi-agente Salomão.

    Orquestra HeimdallTriageAgent, KnowledgeRagAgent e HelpdeskActionAgent
    em um `agno.team.Team` com modo `coordinate` (supervisor-worker).

    Args:
        session_id: Identificador único da sessão, tipicamente `f"user-{user.pk}"`.
        user_metadata: Dados do usuário Django sem ORM (nome, e-mail, church_id, etc.).
        mcp_tools: Lista de MCPTools para o HelpdeskActionAgent. Opcional.
        extra_mcp_configs: Configurações MCP adicionais. Opcional.
    """

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
        mcp_tools: list | None = None,
        extra_mcp_configs: list[MCPServerConfig] | None = None,
    ) -> None:
        self.session_id = session_id
        self.user_metadata = user_metadata
        self._logger = structlog.get_logger(self.__class__.__name__).bind(
            session_id=session_id,
            user_id=user_metadata.get("user_id"),
        )

        # --- Instanciação dos sub-agentes ---
        # Cada agente recebe o mesmo session_id para compartilhar o estado
        # Redis da sessão, permitindo que o histórico flua entre eles.
        self._triage = HeimdallTriageAgent(
            session_id=session_id,
            user_metadata=user_metadata,
        )
        self._rag = KnowledgeRagAgent(
            session_id=session_id,
            user_metadata=user_metadata,
        )
        self._action = HelpdeskActionAgent(
            session_id=session_id,
            user_metadata=user_metadata,
            mcp_tools=mcp_tools,
            extra_mcp_configs=extra_mcp_configs,
        )

        # --- Montagem do Team Agno ---
        # TeamMode.coordinate: o model do Team atua como maestro — decide quais
        # membros acionar, agrega as respostas e gera a síntese final.
        channel = self.user_metadata.get("originating_channel", "desconhecido")
        dynamic_routing = []
        if channel == "webchat_central":
            dynamic_routing = [
                "ATENÇÃO: Este usuário está na Central de Ajuda (Webchat).",
                "NÃO chame o HelpdeskActionAgent para atualizar tickets do HubSpot, pois não há ticket ativo.",
                "Mantenha as respostas extremamente curtas.",
            ]
        else:
            dynamic_routing = [
                "ATENÇÃO: Este usuário veio pelo HubSpot.",
                "Faça o transbordo via HelpdeskActionAgent (atualizando o ticket) sempre que o problema não puder ser resolvido pela IA.",
            ]

        instructions = (
            _SUPERVISOR_INSTRUCTIONS
            + dynamic_routing
            + [
                "FLUXO DE TRANSBORDO DO RAG:",
                "Se a resposta devolvida pelo KnowledgeRagAgent contiver a tag <REQUIRES_ESCALATION>, significa que a Inteligência não pôde sanar a dúvida.",
                "Neste cenário, ANTES DE RESPONDER AO USUÁRIO, você DEVE delegar a tarefa para o HelpdeskActionAgent com a ordem estrita de atualizar o ticket no HubSpot notificando a necessidade de transbordo da IA para Humanos.",
                "Somente após a confirmação do HelpdeskActionAgent, formule sua resposta final pedindo desculpas e informando o número do protocolo do ticket formatado.",
            ]
        )

        self._team = Team(
            id="salomao-supervisor",
            name="Salomão",
            mode=TeamMode.coordinate,
            model=build_primary_model(),
            fallback_config=_build_fallback_config(),
            db=_build_redis_db(session_id),
            members=[self._triage, self._rag, self._action],
            instructions=instructions,
            session_id=session_id,
            # Propaga o histórico do Team para os membros, permitindo
            # que cada sub-agente saiba o que os outros já disseram.
            add_team_history_to_members=True,
            num_team_history_runs=3,
            markdown=True,
            telemetry=False,
        )

        self._logger.info("supervisor_initialized", team_mode=TeamMode.coordinate)

    @property
    def team(self) -> Team:
        """Return the underlying Agno Team for AgentOS/local inspection."""
        return self._team

    # ---------------------------------------------------------------------------
    # Interface pública
    # ---------------------------------------------------------------------------

    def run_pipeline(
        self,
        message: str,
        *,
        stream: bool = False,
    ) -> SalomaoResponse:
        """Executa o pipeline completo de atendimento para uma mensagem do usuário.

        Ponto de entrada principal para a API Django Ninja. Delega ao Team Agno
        a orquestração dos sub-agentes e formata a saída como `SalomaoResponse`.

        Args:
            message: Mensagem recebida do usuário (texto livre).
            stream: Se True, usa streaming interno do Agno (resposta ainda é
                retornada completa — streaming é para otimização interna do Team).

        Returns:
            SalomaoResponse pronto para serialização pelo Django Ninja.

        Raises:
            RuntimeError: Se o Team retornar uma resposta vazia ou inválida.
        """
        import time

        from django.db.models import Sum

        from apps.ai_agents.models import TokenTrackingLog

        start = time.perf_counter()
        self._logger.info("pipeline_start", message_preview=message[:80])

        # 1. Circuit Breaker e Verificação de Primeira Mensagem
        try:
            query = TokenTrackingLog.objects.filter(session_id=self.session_id)
            aggr = query.aggregate(total=Sum("prompt_tokens") + Sum("completion_tokens"))
            total_acumulado = aggr["total"] or 0
            message_count = query.count()

            if total_acumulado > 15000:
                self._logger.warning("circuit_breaker_triggered", session_id=self.session_id, tokens=total_acumulado)
                return SalomaoResponse(
                    session_id=self.session_id,
                    message="Limite técnico da sessão atingido. Por favor, transfira para um atendente ou inicie um novo chat.",
                    sources=[],
                    requires_human_handoff=True,
                    handoff_reason="Token budget exceeded",
                    agent_trace=["circuit_breaker: BLOCKED"],
                    tokens_used=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    model_name="circuit_breaker",
                    latency_ms=0,
                )

            # Dinâmica da Primeira Mensagem (Greeting)
            if message_count == 0:
                greeting_rule = "🚨 REGRA CRÍTICA: Esta é a PRIMEIRA mensagem da sessão. Você DEVE iniciar sua resposta EXATAMENTE com: 'Olá! 👋 Eu sou o Salomão, o seu assistente virtual da inChurch...'. Esta apresentação é obrigatória."
            else:
                greeting_rule = "🚨 REGRA CRÍTICA: Você JÁ se apresentou. NÃO diga 'Olá, sou o Salomão' ou faça apresentações longas de novo nesta resposta. Prossiga a conversa naturalmente."

            # Injeta on-the-fly sem poluir a lista global original entre pools
            if isinstance(self._team.instructions, tuple):
                self._team.instructions = list(self._team.instructions)
            elif self._team.instructions is None:
                self._team.instructions = []

            # Evita acumular a regra se run_pipeline rodar repetidas vezes
            self._team.instructions = [instr for instr in self._team.instructions if "REGRA CRÍTICA" not in str(instr)]
            self._team.instructions.append(greeting_rule)

        except Exception as e:
            self._logger.error("circuit_breaker_failed", error=str(e))

        try:
            team_response = self._team.run(message, stream=stream)
            latency_ms = int((time.perf_counter() - start) * 1000)

            content = self._extract_content(team_response)
            requires_handoff, handoff_reason = self._check_handoff(team_response)
            sources = self._extract_sources(team_response)
            agent_trace = self._build_trace(team_response)
            prompt_tokens, completion_tokens, tokens_used = self._extract_token_breakdown(
                team_response,
            )
            model_name = self._extract_model_name(team_response)

            self._logger.info(
                "pipeline_complete",
                latency_ms=latency_ms,
                requires_handoff=requires_handoff,
                tokens_used=tokens_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=model_name,
            )

            return SalomaoResponse(
                session_id=self.session_id,
                message=content,
                sources=sources,
                requires_human_handoff=requires_handoff,
                handoff_reason=handoff_reason,
                agent_trace=agent_trace,
                tokens_used=tokens_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=model_name,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            self._logger.error("pipeline_error", error=str(exc), latency_ms=latency_ms)
            raise

    async def run_pipeline_async(
        self,
        message: str,
        *,
        stream: bool = False,
    ) -> SalomaoResponse:
        """Executa o pipeline de forma assíncrona para suportar MCP tools.

        Wrapper assíncrono do run_pipeline() que delega para o Team.run()
        em modo async, necessário quando há ferramentas MCP que fazem
        chamadas assíncronas a APIs externas.

        Args:
            message: Mensagem recebida do usuário.
            stream: Se True, usa streaming interno do Agno.

        Returns:
            SalomaoResponse formatada.
        """
        import asyncio
        import functools

        # Executa o pipeline síncrono em thread separada para não bloquear a
        # event loop do Django. `stream` é keyword-only em run_pipeline, então
        # usamos functools.partial para evitar TypeError ao passar via executor.
        # get_running_loop() é o método correto dentro de contextos async (3.10+).
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(self.run_pipeline, message, stream=stream))

    # ---------------------------------------------------------------------------
    # Helpers de extração de resposta
    # ---------------------------------------------------------------------------

    def _extract_content(self, response: Any) -> str:
        """Extrai o texto da resposta do Team Agno."""
        if hasattr(response, "content") and response.content:
            return str(response.content)
        if isinstance(response, str):
            return response
        return str(response)

    def _check_handoff(self, response: Any) -> tuple[bool, str | None]:
        """Verifica se o pipeline sinalizou necessidade de transbordo humano.

        Analisa o conteúdo da resposta buscando sinalizadores de handoff
        inseridos pelo HeimdallTriageAgent ou pelo próprio Supervisor.
        """
        content = self._extract_content(response).lower()
        handoff_keywords = [
            "transbordo",
            "escalado",
            "suporte humano",
            "atendente humano",
            "requires_human_handoff",
        ]
        requires_handoff = any(kw in content for kw in handoff_keywords)
        reason = "Situação identificada como crítica ou fora do escopo da IA." if requires_handoff else None
        return requires_handoff, reason

    def _extract_sources(self, response: Any) -> list[dict[str, Any]]:
        """Extrai as fontes (artigos KB) referenciadas na resposta."""
        sources: list[dict[str, Any]] = []
        if hasattr(response, "messages"):
            for msg in response.messages or []:
                if hasattr(msg, "tool_calls"):
                    for tc in msg.tool_calls or []:
                        if "knowledge" in str(tc).lower() or "pinecone" in str(tc).lower():
                            sources.append({"tool_call": str(tc)[:120]})
        return sources

    def _build_trace(self, response: Any) -> list[str]:
        """Constrói um trace legível dos agentes que participaram da resposta."""
        trace: list[str] = []
        if hasattr(response, "member_responses"):
            for member_resp in response.member_responses or []:
                agent_name = getattr(member_resp, "agent_name", "unknown")
                trace.append(f"{agent_name}: OK")
        return trace or ["supervisor: OK"]

    def _extract_tokens(self, response: Any) -> int:
        """Extrai o total de tokens usados na execução do pipeline."""
        _prompt, _completion, total = self._extract_token_breakdown(response)
        return total

    def _extract_token_breakdown(self, response: Any) -> tuple[int, int, int]:
        """Retorna (prompt_tokens, completion_tokens, total_tokens).

        O Agno 2.5 expõe `response.metrics` como objeto (RunMetrics) ou dict
        dependendo da versão; cobrimos ambos. Nomes que usamos por prioridade:
        `input_tokens`/`prompt_tokens` para prompt e
        `output_tokens`/`completion_tokens` para completion.
        """
        metrics = getattr(response, "metrics", None)
        if metrics is None:
            return 0, 0, 0

        def _pick(src: Any, names: tuple[str, ...]) -> int:
            for name in names:
                value = src.get(name) if isinstance(src, dict) else getattr(src, name, None)
                if value:
                    return int(value)
            return 0

        prompt = _pick(metrics, ("input_tokens", "prompt_tokens"))
        completion = _pick(metrics, ("output_tokens", "completion_tokens"))
        total = _pick(metrics, ("total_tokens",)) or (prompt + completion)
        return prompt, completion, total

    def _extract_model_name(self, response: Any) -> str:
        """Descobre qual modelo respondeu — usado para cálculo de custo.

        Procura no response primeiro; se não estiver lá, cai no modelo
        configurado no próprio Team.
        """
        for attr in ("model", "model_name"):
            value = getattr(response, attr, None)
            if value:
                return str(value)

        team_model = getattr(self._team, "model", None)
        if team_model is not None:
            for attr in ("id", "name", "model"):
                value = getattr(team_model, attr, None)
                if value:
                    return str(value)
        return ""


# ---------------------------------------------------------------------------
# Agente de suporte — herda Base para compatibilidade com a cadeia de tipos
# ---------------------------------------------------------------------------


class SalomaoDirectAgent(BaseInChurchAgent):
    """Variante de Salomão como agente único (sem Team) para casos simples.

    Use quando a query não precisar de triagem ou ações externas — responde
    diretamente com base na base de conhecimento e no histórico da sessão.
    Útil para smoke tests e ambientes onde os sub-agentes MCP não estão disponíveis.
    """

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
    ) -> None:
        from apps.ai_agents.agents.tools.hubspot_tools import GetTicketInfo
        from apps.ai_agents.agents.tools.knowledge_tools import SearchKnowledgeBase

        super().__init__(
            session_id=session_id,
            user_metadata=user_metadata,
            name="Salomão",
            instructions=[
                "Você é Salomão, o assistente virtual da InChurch.",
                "Responda sempre em português brasileiro.",
                "Use as ferramentas disponíveis para fundamentar suas respostas.",
                "Se não souber a resposta, indique que o usuário pode contatar o suporte humano.",
                "Seja cordial, prestativo e profissional.",
            ],
            tools=[SearchKnowledgeBase(), GetTicketInfo()],
        )
