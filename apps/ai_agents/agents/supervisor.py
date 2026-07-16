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

import json
from typing import Any

import structlog
from agno.team import Team
from agno.team.team import TeamMode
from django.conf import settings
from pydantic import BaseModel

from apps.ai_agents.agents.action import HelpdeskActionAgent, MCPServerConfig
from apps.ai_agents.agents.base import (
    BaseInChurchAgent,
    _build_fallback_config,
    _build_redis_db,
    build_primary_model,
)
from apps.ai_agents.agents.rag import KnowledgeRagAgent
from apps.ai_agents.agents.salomao_chat import SalomaoChatAgent
from apps.ai_agents.agents.triage import HeimdallTriageAgent
from apps.ai_agents.contracts import (
    ConversationContext,
    ConversationMessage,
    HubSpotAction,
    SalomaoChatDraft,
    SupervisorDecision,
    TriageDecision,
)
from apps.integrations.salomao_v1 import is_salomao_v1_configured

logger = structlog.get_logger(__name__)

FIRST_MESSAGE_GREETING = "Olá! 👋 Eu sou o Salomão, o seu assistente virtual da inChurch..."


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
    decision: SupervisorDecision | None = None
    triage_decision: TriageDecision | None = None


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
        db: Any | None = None,
    ) -> None:
        self.session_id = session_id
        self.user_metadata = user_metadata
        self._db = db
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
            db=db,
        )
        self._rag: KnowledgeRagAgent | None = None
        self._build_rag_agent()
        self._action = HelpdeskActionAgent(
            session_id=session_id,
            user_metadata=user_metadata,
            mcp_tools=mcp_tools,
            extra_mcp_configs=extra_mcp_configs,
            db=db,
        )
        self._salomao_chat = (
            SalomaoChatAgent(
                session_id=session_id,
                user_metadata=user_metadata,
                db=db,
            )
            if self._should_enable_salomao_chat_agent()
            else None
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

        salomao_chat_routing = []
        if self._salomao_chat is not None:
            salomao_chat_routing = [
                "CAPACIDADE INTERNA: O membro SalomaoChat encapsula o Salomao v1 como adapter agent.",
                "Depois do Heimdall e antes da resposta final, acione o SalomaoChat para gerar um SalomaoChatDraft quando houver pergunta do cliente.",
                "Use o SalomaoChatDraft para decidir resposta final, dados faltantes e transbordo; nao trate o Salomao v1 como bypass externo.",
                "Se o SalomaoChatDraft indicar requires_human_handoff=true, sintetize a resposta final com handoff humano seguro.",
            ]

        instructions = (
            _SUPERVISOR_INSTRUCTIONS
            + dynamic_routing
            + salomao_chat_routing
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
            db=db or _build_redis_db(session_id),
            members=[member for member in [self._triage, self._rag, self._action, self._salomao_chat] if member],
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

    def _build_rag_agent(self) -> KnowledgeRagAgent | None:
        """Build the RAG member only when a route actually needs it."""
        if self._rag is not None:
            return self._rag

        try:
            self._rag = KnowledgeRagAgent(
                session_id=self.session_id,
                user_metadata=self.user_metadata,
                db=self._db,
            )
        except Exception as exc:
            self._logger.warning("rag_agent_unavailable", error=str(exc))
            return None

        return self._rag

    def _should_enable_salomao_chat_agent(self) -> bool:
        """Return True when Salomao v1 should be exposed as a Team member."""
        return bool(getattr(settings, "SALOMAO_V1_AS_TEAM_AGENT", True)) and is_salomao_v1_configured()

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
        is_first_message = False

        # 1. Circuit Breaker e Verificação de Primeira Mensagem
        try:
            query = TokenTrackingLog.objects.filter(session_id=self.session_id)
            aggr = query.aggregate(total=Sum("prompt_tokens") + Sum("completion_tokens"))
            total_acumulado = aggr["total"] or 0
            message_count = query.count()
            is_first_message = message_count == 0

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
                    decision=SupervisorDecision(
                        outcome="escalate_human",
                        final_response=(
                            "Limite técnico da sessão atingido. "
                            "Vou encaminhar o atendimento para uma pessoa do nosso time."
                        ),
                        trace_summary=["circuit_breaker: BLOCKED"],
                        risk_flags=["token_budget_exceeded"],
                        confidence=1.0,
                    ),
                )

            # Dinâmica da Primeira Mensagem (Greeting)
            if is_first_message:
                greeting_rule = f"🚨 REGRA CRÍTICA: Esta é a PRIMEIRA mensagem da sessão. Você DEVE iniciar sua resposta EXATAMENTE com: '{FIRST_MESSAGE_GREETING}'. Esta apresentação é obrigatória."
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
            deterministic_response = self._run_integrated_chain(message)
            if deterministic_response is not None:
                latency_ms = int((time.perf_counter() - start) * 1000)
                return self._finalize_response(
                    SalomaoResponse(
                        session_id=self.session_id,
                        message=deterministic_response.message,
                        sources=deterministic_response.sources,
                        requires_human_handoff=deterministic_response.requires_human_handoff,
                        handoff_reason=deterministic_response.handoff_reason,
                        agent_trace=deterministic_response.agent_trace,
                        tokens_used=deterministic_response.tokens_used,
                        prompt_tokens=deterministic_response.prompt_tokens,
                        completion_tokens=deterministic_response.completion_tokens,
                        model_name=deterministic_response.model_name,
                        latency_ms=latency_ms,
                        decision=deterministic_response.decision,
                        triage_decision=deterministic_response.triage_decision,
                    ),
                    is_first_message=is_first_message,
                )

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
            decision = SupervisorDecision(
                outcome="escalate_human" if requires_handoff else "waiting_customer",
                final_response=content,
                trace_summary=agent_trace,
                risk_flags=["unstructured_team_handoff"] if requires_handoff else ["unstructured_team_fallback"],
                confidence=0.5 if requires_handoff else 0.4,
            )

            self._logger.info(
                "pipeline_complete",
                latency_ms=latency_ms,
                requires_handoff=requires_handoff,
                tokens_used=tokens_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_name=model_name,
            )

            return self._finalize_response(
                SalomaoResponse(
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
                    decision=decision,
                ),
                is_first_message=is_first_message,
            )

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            self._logger.error("pipeline_error", error=str(exc), latency_ms=latency_ms)
            raise

    def _finalize_response(self, response: SalomaoResponse, *, is_first_message: bool) -> SalomaoResponse:
        """Enforce response invariants that must not depend on model compliance."""
        if not is_first_message or response.message.startswith(FIRST_MESSAGE_GREETING):
            return response

        response.message = f"{FIRST_MESSAGE_GREETING}\n\n{response.message.lstrip()}"
        return response

    def _run_integrated_chain(self, message: str) -> SalomaoResponse | None:
        """Run the required Heimdall -> SalomaoChat path deterministically.

        The Agno Team remains available for AgentOS exploration and fallback,
        but production routing must not depend on the LLM deciding to call a
        member/tool. Heimdall and the Salomao v1 adapter are therefore called
        explicitly when the adapter is enabled.
        """
        trace = []
        try:
            triage_response = self._triage.run(message)
            triage = self._extract_triage_decision(triage_response)
            trace.append("heimdall: OK")
        except Exception as exc:
            self._logger.error("heimdall_triage_failed", error=str(exc))
            triage = None
            trace.append("heimdall: failed")

        if triage is None:
            return self._failed_triage_response(agent_trace=trace)

        if triage.dados_faltantes:
            trace.append("supervisor: waiting_for_missing_data")
            return self._missing_data_response(triage=triage, agent_trace=trace)

        if self._requires_mandatory_handoff(triage):
            trace.append("supervisor: mandatory_human_handoff")
            return self._mandatory_handoff_response(triage=triage, agent_trace=trace)

        context = self._build_conversation_context(message)
        if context.missing_context:
            trace.append("supervisor: waiting_for_context")
            return self._missing_data_response(
                triage=triage,
                agent_trace=trace,
                missing_data=context.missing_context,
            )

        if triage.rota in {"DUVIDAS_PLATAFORMA", "ATENDIMENTO_IA"}:
            rag = self._build_rag_agent()
            if rag is not None:
                try:
                    rag_response = rag.run(message)
                    content = self._extract_content(rag_response)
                    requires_handoff, handoff_reason = self._check_handoff(rag_response)
                    trace.append("knowledge_rag: OK")
                    return self._response_from_specialized_service(
                        content=content,
                        triage=triage,
                        agent_trace=trace,
                        requires_handoff=requires_handoff,
                        handoff_reason=handoff_reason,
                        sources=self._extract_sources(rag_response),
                        model_name=self._extract_response_model_name(rag_response) or "knowledge_rag",
                    )
                except Exception as exc:
                    self._logger.error("knowledge_rag_failed", error=str(exc))
                    trace.append("knowledge_rag: failed")

        if self._salomao_chat is None:
            return None

        draft = self._salomao_chat.create_chat_draft(
            message=message,
            triage_decision=triage,
            conversation_context=context,
        )

        trace.append("salomao_chat: OK")
        if draft.recommended_actions:
            trace.append("helpdesk_action: pending_supervisor_decision")

        return self._response_from_salomao_draft(draft, trace, triage=triage)

    def _requires_mandatory_handoff(self, triage: TriageDecision | None) -> bool:
        """Return True when the triage contract forbids an automated answer."""
        if triage is None:
            return False
        return (
            triage.rota == "ESCALAR_IMEDIATAMENTE"
            or triage.prioridade in {"ALTA", "CRITICA"}
            or triage.sentimento == "negativo"
            or triage.confidence < 0.6
        )

    def _mandatory_handoff_response(
        self,
        *,
        triage: TriageDecision | None,
        agent_trace: list[str],
    ) -> SalomaoResponse:
        """Build the fixed response for triage decisions that require escalation."""
        reason = "Heimdall classified the ticket as requiring immediate human handoff."
        if triage and triage.prioridade in {"ALTA", "CRITICA"}:
            reason = f"Heimdall classified the ticket as {triage.prioridade}."
        elif triage and triage.sentimento == "negativo":
            reason = "Heimdall detected customer frustration."
        elif triage and triage.confidence < 0.6:
            reason = "Heimdall confidence is below the automated-service threshold."

        frustrated = bool(triage and triage.sentimento == "negativo")
        message = (
            "Entendo como essa situação é frustrante e sinto muito pelo transtorno. "
            "Para que você receba a atenção necessária, vou encaminhar seu atendimento "
            "para uma pessoa do nosso time, que continuará por aqui com o contexto que você já enviou."
            if frustrated
            else "Sinto muito pelo transtorno. Como este caso precisa de uma atenção mais cuidadosa, "
            "vou encaminhar seu atendimento para uma pessoa do nosso time, que continuará por aqui "
            "com o contexto que você já enviou."
        )

        return SalomaoResponse(
            session_id=self.session_id,
            message=message,
            sources=[],
            requires_human_handoff=True,
            handoff_reason=reason,
            agent_trace=agent_trace,
            tokens_used=0,
            prompt_tokens=0,
            completion_tokens=0,
            model_name="heimdall_triage",
            latency_ms=0,
            triage_decision=triage,
            decision=SupervisorDecision(
                outcome="escalate_human",
                final_response=message,
                hubspot_action=HubSpotAction(
                    action_type="assign_ticket_to_human_queue",
                    payload={"reason": reason},
                    idempotency_key=f"{self.session_id}:human-handoff",
                ),
                trace_summary=agent_trace,
                risk_flags=self._risk_flags(triage),
                confidence=triage.confidence if triage else 0.0,
            ),
        )

    def _failed_triage_response(self, *, agent_trace: list[str]) -> SalomaoResponse:
        """Fail safely when the triage contract cannot be produced."""
        message = (
            "Não consegui classificar seu atendimento com segurança agora. "
            "Vou encaminhar a conversa para uma pessoa do nosso time."
        )
        return SalomaoResponse(
            session_id=self.session_id,
            message=message,
            sources=[],
            requires_human_handoff=True,
            handoff_reason="Heimdall triage failed or returned an invalid contract.",
            agent_trace=agent_trace,
            tokens_used=0,
            model_name="heimdall_triage",
            latency_ms=0,
            decision=SupervisorDecision(
                outcome="escalate_human",
                final_response=message,
                trace_summary=agent_trace,
                risk_flags=["triage_contract_failure"],
                confidence=0.0,
            ),
        )

    def _missing_data_response(
        self,
        *,
        triage: TriageDecision,
        agent_trace: list[str],
        missing_data: list[str] | None = None,
    ) -> SalomaoResponse:
        """Ask one focused question and wait for the customer."""
        fields = missing_data or triage.dados_faltantes
        first_field = fields[0] if fields else "informação necessária"
        readable = first_field.replace("_", " ")
        message = f"Para continuar com segurança, preciso que você informe: {readable}."
        return SalomaoResponse(
            session_id=self.session_id,
            message=message,
            sources=[],
            requires_human_handoff=False,
            handoff_reason=None,
            agent_trace=agent_trace,
            tokens_used=0,
            model_name="heimdall_triage",
            latency_ms=0,
            triage_decision=triage,
            decision=SupervisorDecision(
                outcome="waiting_customer",
                final_response=message,
                hubspot_action=HubSpotAction(
                    action_type="send_thread_reply",
                    payload={"missing_data": fields},
                    idempotency_key=f"{self.session_id}:missing-data:{first_field}",
                ),
                trace_summary=agent_trace,
                missing_data=fields,
                confidence=triage.confidence,
            ),
        )

    def _build_conversation_context(self, message: str) -> ConversationContext:
        """Build provider-neutral context for agent handoffs."""
        raw_context = self.user_metadata.get("conversation_context")
        if isinstance(raw_context, ConversationContext):
            return raw_context
        if isinstance(raw_context, dict):
            try:
                return ConversationContext.model_validate(raw_context)
            except Exception as exc:
                self._logger.warning("conversation_context_invalid", error=str(exc))

        channel = self.user_metadata.get("originating_channel", "api")
        if channel not in {"hubspot", "webchat_central", "api"}:
            channel = "api"
        return ConversationContext(
            channel=channel,
            session_id=self.session_id,
            ticket_id=self.user_metadata.get("hubspot_ticket_id"),
            thread_id=self.user_metadata.get("hubspot_thread_id"),
            contact_id=self.user_metadata.get("hubspot_contact_id"),
            church_id=self.user_metadata.get("church_id"),
            recent_messages=[
                ConversationMessage(
                    direction="INCOMING",
                    text=message,
                )
            ],
            allowed_actions=[
                "send_thread_reply",
                "assign_ticket_to_human_queue",
                "add_internal_note",
            ],
        )

    def _extract_triage_decision(self, response: Any) -> TriageDecision | None:
        """Normalize Heimdall output into the shared triage contract."""
        content = getattr(response, "content", response)
        if isinstance(content, TriageDecision):
            return content
        if hasattr(content, "model_dump"):
            try:
                return TriageDecision.model_validate(content.model_dump(mode="json"))
            except TypeError:
                return TriageDecision.model_validate(content.model_dump())
            except Exception as exc:
                self._logger.warning("triage_decision_invalid", error=str(exc))
                return None
        if isinstance(content, dict):
            try:
                return TriageDecision.model_validate(content)
            except Exception as exc:
                self._logger.warning("triage_decision_invalid", error=str(exc))
                return None
        if isinstance(content, str):
            try:
                return TriageDecision.model_validate(json.loads(content))
            except Exception as exc:
                self._logger.warning("triage_decision_unparseable", error=str(exc))
                return None
        return None

    def _response_from_salomao_draft(
        self,
        draft: SalomaoChatDraft,
        agent_trace: list[str],
        *,
        triage: TriageDecision | None = None,
    ) -> SalomaoResponse:
        """Convert the SalomaoChatDraft contract into the public API response."""
        effective_triage = triage or TriageDecision(
            rota="ATENDIMENTO_IA",
            prioridade="MEDIA",
            sentimento="neutro",
        )
        if draft.missing_data:
            return self._missing_data_response(
                triage=effective_triage,
                agent_trace=[*agent_trace, "supervisor: waiting_for_missing_data"],
                missing_data=draft.missing_data,
            )

        if draft.requires_human_handoff or draft.confidence < 0.6:
            outcome = "escalate_human"
            requires_handoff = True
            handoff_reason = draft.handoff_reason or "Specialized service confidence is below threshold."
            message = draft.response_text
        elif draft.resolved:
            outcome = "candidate_resolved"
            requires_handoff = False
            handoff_reason = None
            message = self._append_resolution_confirmation(draft.response_text)
        else:
            outcome = "waiting_customer"
            requires_handoff = False
            handoff_reason = None
            message = draft.response_text

        return SalomaoResponse(
            session_id=self.session_id,
            message=message,
            sources=[],
            requires_human_handoff=requires_handoff,
            handoff_reason=handoff_reason,
            agent_trace=agent_trace,
            tokens_used=draft.total_tokens or draft.prompt_tokens + draft.completion_tokens,
            prompt_tokens=draft.prompt_tokens,
            completion_tokens=draft.completion_tokens,
            model_name=draft.model_name or "salomao_v1",
            latency_ms=0,
            triage_decision=effective_triage,
            decision=SupervisorDecision(
                outcome=outcome,
                final_response=message,
                hubspot_action=HubSpotAction(
                    action_type=("assign_ticket_to_human_queue" if requires_handoff else "send_thread_reply"),
                    payload={
                        "recommended_actions": [action.model_dump(mode="json") for action in draft.recommended_actions]
                    },
                    idempotency_key=f"{self.session_id}:supervisor:{outcome}",
                ),
                trace_summary=agent_trace,
                risk_flags=self._risk_flags(effective_triage),
                confidence=draft.confidence,
            ),
        )

    def _response_from_specialized_service(
        self,
        *,
        content: str,
        triage: TriageDecision,
        agent_trace: list[str],
        requires_handoff: bool,
        handoff_reason: str | None,
        sources: list[dict[str, Any]],
        model_name: str,
    ) -> SalomaoResponse:
        """Build a structured decision from a deterministic service route."""
        outcome = "escalate_human" if requires_handoff else "candidate_resolved"
        message = content if requires_handoff else self._append_resolution_confirmation(content)
        return SalomaoResponse(
            session_id=self.session_id,
            message=message,
            sources=sources,
            requires_human_handoff=requires_handoff,
            handoff_reason=handoff_reason,
            agent_trace=agent_trace,
            tokens_used=0,
            model_name=model_name,
            latency_ms=0,
            triage_decision=triage,
            decision=SupervisorDecision(
                outcome=outcome,
                final_response=message,
                trace_summary=agent_trace,
                risk_flags=self._risk_flags(triage),
                confidence=triage.confidence,
            ),
        )

    def _append_resolution_confirmation(self, content: str) -> str:
        """Ensure candidate resolutions request deterministic confirmation."""
        normalized = content.rstrip()
        question = "Isso resolveu sua solicitação?"
        if question.lower() in normalized.lower():
            return normalized
        return f"{normalized}\n\n{question}"

    def _risk_flags(self, triage: TriageDecision | None) -> list[str]:
        """Translate triage dimensions into stable risk flags."""
        if triage is None:
            return ["triage_missing"]
        flags: list[str] = []
        if triage.prioridade in {"ALTA", "CRITICA"}:
            flags.append(f"priority_{triage.prioridade.lower()}")
        if triage.sentimento == "negativo":
            flags.append("negative_sentiment")
        if triage.confidence < 0.6:
            flags.append("low_confidence")
        return flags

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

    def _extract_response_model_name(self, response: Any) -> str:
        """Extract a model name without falling back to the Supervisor model."""
        for attr in ("model", "model_name"):
            value = getattr(response, attr, None)
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
