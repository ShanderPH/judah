"""HeimdallTriageAgent — Triagem estruturada (contrato legado N8N).

O contrato de saída replica exatamente o JSON produzido pelo fluxo N8N
histórico do Heimdall, para que o Supervisor possa rotear de forma
determinística com base no campo `rota`. Campos e enums seguem o legado:
`rota`, `prioridade`, `tags`, `dados_faltantes`, `sentimento`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from apps.ai_agents.agents.base import BaseInChurchAgent, build_mini_model

# ---------------------------------------------------------------------------
# Schema de Saída Estruturada (contrato legado N8N)
# ---------------------------------------------------------------------------


class Rota(StrEnum):
    """Filas/rotas finais decididas pela triagem."""

    BOLETO = "BOLETO"
    EVENTOS = "EVENTOS"
    DUVIDAS_PLATAFORMA = "DUVIDAS_PLATAFORMA"
    MEIOS_DE_PAGAMENTO = "MEIOS_DE_PAGAMENTO"
    FINANCEIRO = "FINANCEIRO"
    SUPORTE_TECNICO_N1 = "SUPORTE_TECNICO_N1"
    CUSTOMER_SUCCESS = "CUSTOMER_SUCCESS"
    ESCALAR_IMEDIATAMENTE = "ESCALAR_IMEDIATAMENTE"
    ATENDIMENTO_IA = "ATENDIMENTO_IA"


class Prioridade(StrEnum):
    """Prioridade do atendimento (seguindo taxonomia N8N)."""

    CRITICA = "CRITICA"
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


class Sentimento(StrEnum):
    """Sentimento predominante detectado na mensagem (minúsculas no legado)."""

    POSITIVO = "positivo"
    NEUTRO = "neutro"
    NEGATIVO = "negativo"


class TriageResult(BaseModel):
    """Saída estruturada do HeimdallTriageAgent — contrato legado N8N.

    Todos os campos são obrigatórios para forçar o LLM a raciocinar
    explicitamente sobre cada dimensão antes de responder. O Supervisor
    lê `rota` para decidir a delegação (RAG, Action ou escalonamento humano).
    """

    # OpenAI rejects JSON Schema properties that combine an enum $ref with
    # sibling keywords such as description. The enum classes document values.
    rota: Rota
    prioridade: Prioridade
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Lista de tags curtas em snake_case que sumarizam a mensagem "
            "(ex: 'segunda_via_boleto', 'culto_ao_vivo', 'login_bloqueado')."
        ),
    )
    dados_faltantes: list[str] = Field(
        default_factory=list,
        description=(
            "Dados que o usuário ainda não forneceu e que serão necessários "
            "para resolver o caso (ex: 'cpf', 'id_do_ticket', 'nome_da_igreja')."
        ),
    )
    sentimento: Sentimento
    confidence: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Confiança calibrada da classificação.",
    )
    evidences: list[str] = Field(
        default_factory=list,
        description="Trechos curtos da mensagem que sustentam a classificação.",
    )
    policy_version: str = Field(
        default="heimdall-v1",
        description="Versão da política de triagem aplicada.",
    )


# ---------------------------------------------------------------------------
# System Prompt — Regras Legadas do N8N
# ---------------------------------------------------------------------------

_TRIAGE_INSTRUCTIONS = """Você é Heimdall, o guardião/triagem do suporte InChurch.

OBJETIVO
Classificar a mensagem recebida e preencher EXATAMENTE o schema JSON
(`rota`, `prioridade`, `tags`, `dados_faltantes`, `sentimento`). Você NUNCA
responde ao usuário — você apenas classifica para que o Supervisor decida o
próximo passo.

MENUS NUMERADOS (legado do atendimento inicial)
Se a mensagem contiver APENAS um dígito (ou começar com ele seguido de um
marcador tipo "1.", "1)", "1 -"), aplique o mapeamento:
  - "1" → rota = BOLETO
  - "2" → rota = EVENTOS
  - "3" → rota = DUVIDAS_PLATAFORMA

REGRAS POR PALAVRAS-CHAVE (aplique na ordem; a primeira que casar vence)
1. Falou em "cancelar", "reembolso", "cobrança indevida", "estorno", "débito
   automático", "cartão clonado" → rota = FINANCEIRO.
2. Falou em "boleto", "segunda via", "vencimento", "nota fiscal" → rota = BOLETO.
3. Falou em "cartão", "pix", "gateway", "stripe", "pagar.me", "checkout" →
   rota = MEIOS_DE_PAGAMENTO.
4. Falou em "culto ao vivo", "transmissão", "live", "evento", "ingresso",
   "inscrição", "check-in do evento" → rota = EVENTOS.
5. Falou em "bug", "erro", "travou", "não carrega", "tela branca", "login",
   "senha", "app fechou", "aplicativo crashando" → rota = SUPORTE_TECNICO_N1.
6. Pediu orientação de uso, "como faço", "onde encontro", "como configurar",
   "tutorial" → rota = DUVIDAS_PLATAFORMA.
7. Onboarding, sucesso do cliente, reunião estratégica, renovação de contrato,
   upsell → rota = CUSTOMER_SUCCESS.
8. Sem palavra-chave clara, porém a pergunta é respondível por base de
   conhecimento → rota = ATENDIMENTO_IA.

PRIORIDADE
- CRITICA: transmissão ao vivo caída DURANTE o culto, acesso bloqueado em
  dia de evento, perda financeira imediata, dados sensíveis vazados,
  múltiplas igrejas afetadas, ou qualquer cenário em que o cliente
  mencionar que o problema está acontecendo AGORA em um culto/evento.
- ALTA: bug bloqueante sem workaround, reembolso urgente, boleto vencendo
  hoje/amanhã, frustração explícita do cliente.
- MEDIA: dúvidas operacionais, configurações, funcionalidades que não
  bloqueiam operação.
- BAIXA: curiosidades, elogios, agradecimentos, pedidos de feature.

DETECÇÃO DE FRUSTRAÇÃO → ESCALAR_IMEDIATAMENTE
Se identificar insultos, ameaça de cancelamento ("vou cancelar", "vou
processar"), menção a redes sociais/Procon/imprensa, caixa alta agressiva,
ou três tentativas fracassadas mencionadas pelo usuário → rota =
ESCALAR_IMEDIATAMENTE e prioridade = CRITICA. Nesses casos, `sentimento`
deve ser "negativo".

SENTIMENTO
- positivo: elogios, agradecimentos, tom amigável.
- neutro: perguntas objetivas sem carga emocional.
- negativo: reclamação, frustração, urgência com tom duro.

CONFIANÇA, EVIDÊNCIAS E POLÍTICA
- `confidence`: número entre 0 e 1. Use valores abaixo de 0.60 quando a
  classificação estiver ambígua ou depender de contexto ausente.
- `evidences`: até 3 trechos curtos presentes na mensagem que justificam rota,
  prioridade ou sentimento. Nunca invente evidências.
- `policy_version`: retorne exatamente "heimdall-v1".

TAGS
- Use snake_case, curto e descritivo (máx 4 tags).
- Exemplos: "segunda_via_boleto", "transmissao_ao_vivo", "login_bloqueado",
  "pix_checkout", "cancelamento_plano".

DADOS FALTANTES
- Liste somente o que AINDA NÃO foi informado e seria necessário para
  resolver (ex: "cpf", "id_do_ticket", "nome_da_igreja", "print_do_erro").
- Se já houver tudo que é necessário, retorne lista vazia [].

REGRA DE OURO
Nunca invente dados. Se um campo não estiver presente na mensagem, NÃO o
inclua em `tags` ou `dados_faltantes`. Responda SOMENTE o JSON do schema.
"""


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------


class HeimdallTriageAgent(BaseInChurchAgent):
    """Agente de triagem com Structured Output (contrato legado N8N).

    Usa `output_schema=TriageResult` + `structured_outputs=True` para que o
    Agno valide a resposta do LLM via Pydantic antes de retornar ao chamador.

    Roda em modelo mini (`DEFAULT_MINI_MODEL`) porque triagem é de alta
    frequência e baixo custo cognitivo. O Supervisor (`gpt-4o`) assume o
    raciocínio mais complexo só depois de receber a rota.
    """

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
        db: Any | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if db is not None:
            kwargs["db"] = db

        super().__init__(
            session_id=session_id,
            user_metadata=user_metadata,
            name="Heimdall",
            model=build_mini_model(),
            instructions=_TRIAGE_INSTRUCTIONS,
            output_schema=TriageResult,
            structured_outputs=True,
            # Triagem é atômica — sem histórico.
            add_history_to_context=False,
            debug_mode=False,
            **kwargs,
        )
