# Plano de upgrade das integracoes dos agentes

> Inicio / [Visao geral](../README.md) / [IA](./README.md)

## Resumo

Este documento propoe a evolucao do ecossistema Salomao para transformar a bridge externa `SALOMAO_V1_BASE_URL` em um agente membro do `SalomaoSupervisorAgent`, removendo o desvio atual em que o endpoint Django decide chamar o servico externo antes de entrar no `Team` do Agno.

A arquitetura alvo mantem o Supervisor como orquestrador unico e move a comunicacao para handoffs internos tipados:

```text
Entrada do usuario ou HubSpot
  -> SalomaoSupervisorAgent
  -> HeimdallTriageAgent
  -> HelpdeskActionAgent coleta contexto da conversa/ticket
  -> SalomaoChatAgent gera resposta e plano de atendimento
  -> Supervisor avalia conclusao, risco e necessidade de handoff
  -> HelpdeskActionAgent atualiza HubSpot ou escala para humano
  -> resposta final e trace persistido
```

O objetivo e preservar o valor do Salomao v1, mas integra-lo como capacidade interna observavel, testavel e governada pelo mesmo runtime de agentes.

## Estado atual

Hoje existem dois caminhos concorrentes:

1. O endpoint `POST /api/v1/ai/salomao/chat` em [`apps/ai_agents/api/routers.py`](../../apps/ai_agents/api/routers.py) verifica `is_salomao_v1_configured()`.
2. Se `SALOMAO_V1_BASE_URL` estiver preenchido, o Judah chama `send_chat_to_salomao_v1()` em [`apps/integrations/salomao_v1/client.py`](../../apps/integrations/salomao_v1/client.py) e retorna sem instanciar o Supervisor.
3. Se a bridge externa nao estiver configurada, o endpoint instancia [`SalomaoSupervisorAgent`](../../apps/ai_agents/agents/supervisor.py), que monta um `agno.team.Team` em modo `coordinate` com `HeimdallTriageAgent`, `KnowledgeRagAgent` e `HelpdeskActionAgent`.

Esse desenho acelera fallback para o servico v1, mas cria problemas de produto e engenharia:

- A decisao entre v1 e Team acontece fora do runtime de agentes.
- Heimdall pode ser ignorado no caminho v1.
- A coleta de contexto do HubSpot fica separada da geracao da resposta.
- O Supervisor nao recebe um contrato rico para decidir se a conversa foi concluida.
- Observabilidade, tracing, custo e escalonamento ficam fragmentados entre bridge HTTP, Celery e Team Agno.
- Testar a cadeia completa no AgentOS fica dificil, porque o v1 externo nao aparece como componente do Team.

## Arquitetura alvo

### Componentes

| Componente | Tipo alvo | Responsabilidade |
|------------|-----------|------------------|
| `SalomaoSupervisorAgent` | `Team` Agno em modo `coordinate` | Orquestrar o fluxo completo, decidir conclusao ou escalacao e produzir a resposta final. |
| `HeimdallTriageAgent` | Agente com saida estruturada | Classificar rota, prioridade, sentimento, tags e dados faltantes. |
| `ConversationContextAgent` ou extensao do `HelpdeskActionAgent` | Agente/tool executor | Hidratar conversa, ticket, contato, historico e metadados operacionais do HubSpot. |
| `SalomaoChatAgent` | Novo agente membro | Encapsular a capacidade do Salomao v1 como agente interno, inicialmente via client HTTP, depois via implementacao nativa. |
| `HelpdeskActionAgent` | Agente/tool executor via MCP | Atualizar ticket, enviar reply, mover pipeline, registrar escalonamento e garantir idempotencia. |
| `KnowledgeRagAgent` | Agente especialista | Responder duvidas de plataforma com Pinecone quando Heimdall indicar rota de conhecimento. |

### Fluxo alvo recomendado

```text
1. Supervisor recebe mensagem e metadados do canal.
2. Supervisor chama Heimdall obrigatoriamente.
3. Heimdall retorna TriageDecision tipado.
4. Supervisor chama HelpdeskAction/ConversationContext para obter:
   - ticket_id, thread_id, contato, igreja, owner, pipeline_stage
   - ultimas mensagens relevantes
   - status de horario comercial
   - restricoes de canal
   - dados faltantes e acoes permitidas
5. Supervisor chama SalomaoChatAgent com TriageDecision + ConversationContext.
6. SalomaoChatAgent retorna AtendimentoDraft tipado:
   - resposta sugerida
   - confianca
   - dados que ainda faltam
   - acoes recomendadas
   - deve_escalar
   - motivo_escalacao
7. Supervisor avalia se o atendimento esta concluido:
   - concluido: chama HelpdeskAction para reply e fechamento/espera adequada.
   - nao concluido mas recuperavel: responde pedindo dados faltantes.
   - critico ou fora do escopo: chama HelpdeskAction para escalar ao humano no HubSpot.
8. Supervisor retorna SalomaoResponse com trace, handoff e custos.
```

## Contratos internos sugeridos

Use schemas Pydantic v2 para comunicacao entre agentes. O objetivo e reduzir inferencia livre, facilitar testes e evitar acoplamento com payloads crus do HubSpot ou do Salomao v1.

### `TriageDecision`

```python
class TriageDecision(BaseModel):
    rota: Literal[
        "BOLETO",
        "EVENTOS",
        "DUVIDAS_PLATAFORMA",
        "MEIOS_DE_PAGAMENTO",
        "FINANCEIRO",
        "SUPORTE_TECNICO_N1",
        "CUSTOMER_SUCCESS",
        "ESCALAR_IMEDIATAMENTE",
        "ATENDIMENTO_IA",
    ]
    prioridade: Literal["CRITICA", "ALTA", "MEDIA", "BAIXA"]
    tags: list[str]
    dados_faltantes: list[str]
    sentimento: Literal["positivo", "neutro", "negativo"]
```

O schema ja existe conceitualmente em [`apps/ai_agents/agents/triage.py`](../../apps/ai_agents/agents/triage.py). A melhoria e trata-lo como contrato central do pipeline, nao apenas output local do Heimdall.

### `ConversationContext`

```python
class ConversationContext(BaseModel):
    channel: Literal["hubspot", "webchat_central", "api"]
    session_id: str
    ticket_id: str | None = None
    thread_id: str | None = None
    contact_id: str | None = None
    church_id: str | None = None
    pipeline_id: str | None = None
    pipeline_stage: str | None = None
    owner_id: str | None = None
    is_off_hours: bool = False
    recent_messages: list[ConversationMessage]
    allowed_actions: list[str]
    missing_context: list[str]
```

Esse contrato deve ser montado por servicos de hidratacao ja existentes, como [`apps/ai_agents/services/hubspot.py`](../../apps/ai_agents/services/hubspot.py), e entregue aos agentes sem expor payload bruto do provedor.

### `SalomaoChatDraft`

```python
class SalomaoChatDraft(BaseModel):
    response_text: str
    confidence: float
    resolved: bool
    requires_human_handoff: bool
    handoff_reason: str | None
    missing_data: list[str]
    recommended_actions: list[ActionIntent]
    customer_visible_protocol: str | None
```

No primeiro estagio, `SalomaoChatAgent` pode chamar o Salomao v1 externo e normalizar a resposta nesse contrato. Depois, o client HTTP pode ser removido quando a logica for portada para agentes nativos.

### `SupervisorDecision`

```python
class SupervisorDecision(BaseModel):
    outcome: Literal["resolved", "waiting_customer", "escalate_human", "failed"]
    final_response: str
    hubspot_action: HubSpotAction | None
    trace_summary: list[str]
    risk_flags: list[str]
```

Esse schema deve virar a saida interna do Supervisor antes de converter para `SalomaoResponse`.

## Integracao do Salomao v1 como agente

### Fase 1: Adapter agent

Criar `SalomaoChatAgent` em `apps/ai_agents/agents/salomao_chat.py`.

Responsabilidades:

- Receber `TriageDecision` e `ConversationContext`.
- Chamar `SalomaoV1Client.chat()` quando `SALOMAO_V1_BASE_URL` estiver configurado.
- Normalizar `SalomaoV1ChatResult` para `SalomaoChatDraft`.
- Tratar timeouts, quota, resposta invalida e circuit breaker sem vazar erro de provider.
- Expor `output_schema=SalomaoChatDraft` ou parse explicito validado.

Resultado esperado:

- A bridge externa deixa de ser um `if` no endpoint Django.
- O Supervisor sempre enxerga Heimdall, contexto, resposta sugerida e estado de conclusao.
- O AgentOS consegue testar o Team completo, incluindo o agente adapter.

### Fase 2: Remover bypass dos endpoints

Alterar [`apps/ai_agents/api/routers.py`](../../apps/ai_agents/api/routers.py):

- Remover o bloco que retorna diretamente via `send_chat_to_salomao_v1()`.
- Instanciar sempre o `SalomaoSupervisorAgent` quando `AI_ROUTING_ENABLED=true`.
- Passar `user_metadata` e canal de origem para que o Team decida o caminho correto.

Alterar [`apps/ai_agents/services/__init__.py`](../../apps/ai_agents/services/__init__.py):

- Remover o bypass de `triage_message()` que chama v1 antes de Heimdall.
- Manter Heimdall como primeira etapa deterministica do fluxo.

### Fase 3: Portar logica v1 para nativo

Quando a compatibilidade estiver comprovada:

- Mover prompts, heuristicas e formatacao do Salomao v1 para `SalomaoChatAgent`.
- Substituir chamada HTTP por tools internas, RAG e historico do Team.
- Manter `SalomaoV1Client` apenas como fallback temporario ou remover apos janela de estabilidade.

## Comunicacao interna entre agentes

### Regras propostas

- Todo handoff entre agentes deve usar schema Pydantic versionado.
- O Supervisor nao deve depender de texto livre para decidir escalacao.
- Dados externos devem entrar no Team como `ConversationContext`, nao como payload bruto.
- Ferramentas de escrita no HubSpot devem ser separadas de ferramentas de leitura.
- Acoes irreversiveis precisam de `ActionIntent` explicito, idempotency key e registro de resultado.
- Cada agente deve ter `role` e instrucoes focadas; o Supervisor coordena, mas nao executa tools externas diretamente.

### Contexto compartilhado

Manter `session_id` unico por conversa:

- `user-{id}` para API autenticada.
- `hubspot-ticket-{ticket_id}` para ticket.
- `hubspot-thread-{thread_id}` para conversation thread.

Usar o banco do Agno para historico e tracing quando rodar em AgentOS. Em producao, preferir Postgres/Supabase para traces, sessoes e custos; SQLite deve ficar restrito a dev local.

## HelpdeskAction e HubSpot

O `HelpdeskActionAgent` deve evoluir para duas categorias claras de ferramentas:

### Leitura

- `get_ticket_context`
- `get_thread_context`
- `get_contact_context`
- `get_recent_conversation_messages`
- `get_pipeline_state`

### Escrita

- `send_thread_reply`
- `update_ticket_stage`
- `assign_ticket_to_human_queue`
- `add_internal_note`
- `mark_ai_resolution_attempt`

Regras de seguranca:

- Nunca executar escrita sem `SupervisorDecision`.
- Nunca fechar ticket sem evidencia de resolucao ou confirmacao de acao bem-sucedida.
- Sempre registrar protocolo visivel ao cliente quando houver handoff.
- Em off-hours, aplicar stage e mensagem especificos antes de encerrar a execucao.
- Garantir idempotencia por `ticket_id`, `thread_id`, `message_id` ou chave derivada do evento HubSpot.

## AgentOS e observabilidade

As praticas atuais do Agno recomendam `AgentOS(db=...)` para componentes, sessoes e tracing. Para o JUDAH:

- Dev local: `SqliteDb` em `.agentos/agentos.db`.
- Staging/prod: `PostgresDb` apontando para schema dedicado, se aprovado.
- Ativar `tracing=True` em staging para capturar execucao de Team, members, model calls e tool calls.
- Manter `telemetry=False` quando o objetivo for evitar telemetria externa do Agno.
- Usar `TeamFactory` para montar Teams sob demanda e evitar chamadas a Pinecone/HubSpot no startup.

Checks minimos no AgentOS:

```python
from agno.client import AgentOSClient

client = AgentOSClient(base_url="http://127.0.0.1:7777")
config = client.get_config()
assert "salomao-supervisor" in [team.id for team in config.teams]
```

Execucao manual sugerida:

```python
result = client.run_team(
    team_id="salomao-supervisor",
    message="Meu app travou durante a transmissao ao vivo do culto.",
    session_id="hubspot-ticket-local-123",
)
print(result.content)
```

## Plano de implementacao

### Etapa 1: Preparacao de contratos

- Criar modulo `apps/ai_agents/contracts.py`.
- Mover ou reexportar `TriageResult` como contrato central.
- Adicionar `ConversationContext`, `SalomaoChatDraft`, `SupervisorDecision`, `ActionIntent` e `HubSpotAction`.
- Adicionar testes unitarios de validacao e serializacao.

Critério de aceite:

- Schemas têm testes para payload minimo, payload HubSpot e erro de validacao.
- Nenhum agente consome payload bruto de HubSpot nos novos caminhos.

### Etapa 2: Adapter do Salomao v1

- Criar `SalomaoChatAgent`.
- Encapsular `SalomaoV1Client`.
- Converter resultado externo para `SalomaoChatDraft`.
- Adicionar fallback controlado para erro/timeout.

Critério de aceite:

- Com `SALOMAO_V1_BASE_URL` ativo, o Team usa `SalomaoChatAgent` como membro.
- Heimdall continua sendo chamado antes.
- Testes com `httpx.MockTransport` cobrem sucesso, timeout, erro HTTP e resposta invalida.

### Etapa 3: Context agent e tools de HubSpot

- Separar tools de leitura e escrita.
- Criar servico de contexto com contrato `ConversationContext`.
- Centralizar redaction de dados sensiveis.
- Garantir idempotencia das escritas.

Critério de aceite:

- O fluxo consegue montar contexto para API, ticket e thread.
- Escritas exigem `SupervisorDecision`.
- Tests usam mocks do client HubSpot e nao fazem write real.

### Etapa 4: Supervisor como unico orquestrador

- Remover bypass v1 do endpoint `/salomao/chat`.
- Atualizar instrucoes do Supervisor para o novo fluxo:
  - Heimdall primeiro.
  - Contexto da conversa segundo.
  - Salomao Chat terceiro.
  - Decisao final.
  - HelpdeskAction para reply/fechamento/escalation.
- Substituir deteccao textual de handoff por `SupervisorDecision`.

Critério de aceite:

- `SalomaoResponse.requires_human_handoff` vem de decisao estruturada.
- `agent_trace` mostra todos os membros acionados.
- O endpoint Django e o AgentOS executam o mesmo pipeline.

### Etapa 5: Observabilidade e custos

- Ativar traces no AgentOS de staging.
- Persistir `TokenTrackingLog` por membro do Team, quando disponivel.
- Registrar latencia por etapa.
- Emitir eventos estruturados: `triage_completed`, `context_loaded`, `chat_draft_created`, `hubspot_action_executed`, `supervisor_decision`.

Critério de aceite:

- Cada atendimento tem trace correlacionavel por `session_id`.
- Falhas de tool e model aparecem com `error_code` estavel.
- Metricas por rota e outcome ficam consultaveis.

### Etapa 6: Migracao gradual

- Introduzir feature flag `SALOMAO_V1_AS_TEAM_AGENT=true`.
- Rodar shadow mode: Team gera decisao, mas o caminho antigo ainda responde.
- Comparar outcomes: resposta, handoff, latencia, custo e erro.
- Habilitar por canal ou amostra.
- Remover bridge direta apos estabilidade.

Critério de aceite:

- Sem aumento de handoff indevido.
- Sem duplicidade de replies no HubSpot.
- Sem loops por mensagens `OUTGOING`.
- Rollback documentado para voltar a bridge direta se necessario.

## Estrategia de testes

### Unitarios

- Schemas Pydantic.
- Normalizacao do `SalomaoV1ChatResult`.
- Decisao do Supervisor a partir de drafts controlados.
- Idempotencia de acoes HubSpot.

### Integracao local

- AgentOS sobe com `TeamFactory`.
- `AgentOSClient.run_team()` executa `salomao-supervisor`.
- Mock de Pinecone para rotas de RAG.
- Mock de HubSpot para leitura/escrita.

### Contrato externo

- `SalomaoV1Client` com `httpx.MockTransport`.
- Snapshot de payload enviado a `/chat`.
- Snapshot do contrato `SalomaoChatDraft`.

### E2E controlado

- Evento HubSpot inbound com mensagem nova.
- Hidratacao de contexto.
- Execucao do Team.
- Reply ao HubSpot em mock.
- Escalacao em mock para cenario critico.

## Riscos e mitigacao

| Risco | Mitigacao |
|-------|-----------|
| Duplicidade de resposta no HubSpot | Idempotency key por `thread_id` + `message_id`; ignorar `OUTGOING`; lock Redis. |
| Supervisor ignorar agente obrigatorio | Instrucoes com fluxo rigido + teste de trace + output schema. |
| v1 externo instavel derrubar Team | Circuit breaker no `SalomaoChatAgent`, fallback para handoff humano seguro. |
| Acao de escrita incorreta | Separar leitura/escrita, exigir `SupervisorDecision`, registrar auditoria. |
| Custo alto por multiplos agentes | Modelo mini para Heimdall, short context, cache de contexto, circuit breaker por janela. |
| Pinecone/HubSpot no startup | Usar factories e lazy initialization. |
| Dados sensiveis em logs | Redaction central antes de logs, traces e respostas. |

## Recomendacoes de melhoria

- Criar uma camada de contratos (`contracts.py`) antes de alterar prompts.
- Transformar o Salomao v1 em adapter agent primeiro; portar logica nativa depois.
- Substituir heuristica textual de handoff por decisao estruturada.
- Separar explicitamente tools de leitura e escrita no HubSpot.
- Tornar o Team testavel com fakes de membros para validar fluxo sem LLM.
- Usar tracing do AgentOS em staging antes de producao.
- Persistir custos por membro do Team, nao apenas por resposta final.
- Manter `telemetry=False` por padrao em ambientes sensiveis.
- Documentar e testar rollback da bridge direta.
- Promover o fluxo so depois de comparar shadow runs com o caminho atual.

## Arquivos impactados previstos

- [`apps/ai_agents/agents/supervisor.py`](../../apps/ai_agents/agents/supervisor.py)
- [`apps/ai_agents/agents/action.py`](../../apps/ai_agents/agents/action.py)
- [`apps/ai_agents/agents/triage.py`](../../apps/ai_agents/agents/triage.py)
- `apps/ai_agents/agents/salomao_chat.py` (novo)
- `apps/ai_agents/contracts.py` (novo)
- [`apps/ai_agents/api/routers.py`](../../apps/ai_agents/api/routers.py)
- [`apps/ai_agents/api/webhooks.py`](../../apps/ai_agents/api/webhooks.py)
- [`apps/ai_agents/tasks.py`](../../apps/ai_agents/tasks.py)
- [`apps/integrations/salomao_v1/client.py`](../../apps/integrations/salomao_v1/client.py)
- [`apps/ai_agents/mcp_servers/hubspot_server.py`](../../apps/ai_agents/mcp_servers/hubspot_server.py)
- [`docs/services/ai_agents.md`](../services/ai_agents.md)
- [`docs/architecture/data-flow.md`](../architecture/data-flow.md)

## Sequencia sugerida de PRs

1. `docs(ai): add agent integration upgrade plan`
2. `feat(ai): add typed agent handoff contracts`
3. `feat(ai): add salomao chat adapter agent`
4. `refactor(ai): route salomao chat through supervisor team`
5. `feat(ai): split hubspot read and write action tools`
6. `test(ai): add supervisor team integration coverage`
7. `chore(ai): enable AgentOS tracing in staging`

Essa sequencia reduz risco porque primeiro cria contratos e testes, depois move o v1 para dentro do Team, e so no final remove o bypass antigo.
