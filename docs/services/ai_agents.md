# `apps.ai_agents` — Agentes de IA

## Resumo

Módulo do ecossistema **Salomão**: agentes de IA para atendimento ao cliente, composto por triagem (Heimdall), respostas oficiais do Salomão v1 e ações externas auditadas.

## Contexto

O módulo é opcional e controlado pela feature flag `AI_ROUTING_ENABLED`. Quando desabilitado, o router `/api/v1/ai/` não é montado e as dependências (Agno, Pinecone, MCP) não são carregadas.

## Responsabilidades

- Orquestrar o Supervisor multi-agente.
- Classificar mensagens (Heimdall).
- Delegar todas as respostas ao Salomão v1 após a triagem.
- Executar ações no HubSpot/Jira via MCP.
- Persistir sessões, memórias, traces e custos.
- Receber webhooks do HubSpot e executar pipeline assíncrono.
- Usar o Salomão v1 externo no fluxo determinístico sempre que `SALOMAO_V1_BASE_URL` estiver configurado.

Tambem persiste o lifecycle deterministico de conversas com eventos, transicoes, agent runs e auditoria de tools. O backend controla estado e idempotencia; agentes retornam saidas estruturadas, mas nao alteram lifecycle diretamente.

## Agentes

### `HeimdallTriageAgent`

- Modelo: `DEFAULT_MINI_MODEL` (gpt-5.5).
- Saída estruturada: `TriageResult` (rota, prioridade, tags, dados faltantes,
  sentimento, confiança, evidências e versão da política).
- Sem histórico.

### `KnowledgeRagAgent`

- Modelo: `DEFAULT_MODEL` (gpt-5.5).
- Conectado ao Pinecone via `Knowledge` do Agno.
- Busca automática habilitada.
- Encerra com `<REQUIRES_ESCALATION>` quando não encontra resposta.

### `HelpdeskActionAgent`

- Modelo: `DEFAULT_MODEL`.
- Ferramentas MCP dinâmicas (HubSpot, Jira, n8n placeholders).
- Fallback estático com `GetTicketInfo`, `SearchJiraIssues`, `InChurchDiagnosticsTool`.
- Deve fechar loop atualizando ticket no HubSpot.

### `SalomaoChatAgent`

- Modelo: `DEFAULT_MINI_MODEL`.
- Adapter interno para o servico standalone Salomao v1.
- Usado na produção quando `SALOMAO_V1_BASE_URL` está configurado; `SALOMAO_V1_AS_TEAM_AGENT` controla apenas a exposição no Team exploratório.
- Saida normalizada: `SalomaoChatDraft`.
- Em erro de provider, devolve draft seguro com handoff humano sem vazar tokens, chaves ou stack traces.

### `SalomaoSupervisorAgent`

- Wrapper sobre `agno.team.Team` modo `coordinate`.
- Orquestra o fluxo determinístico Heimdall -> SalomaoChat -> Salomão v1.
- Implementa circuit breaker e greeting injection.
- Saída: `SalomaoResponse` com `SupervisorDecision` restrito a
  `waiting_customer`, `candidate_resolved`, `escalate_human` ou `failed`.

### `SalomaoDirectAgent` (legacy)

- Agente único para smoke tests.

## Contratos tipados

`apps/ai_agents/contracts.py` centraliza os schemas Pydantic usados para handoffs entre agentes:

- `TriageDecision`: rota, prioridade, tags, dados faltantes, sentimento,
  confiança, evidências e versão da política.
- `ConversationContext` / `ConversationMessage`: contexto neutro de provedor (canal, ticket, thread, mensagens recentes).
- `SalomaoChatDraft`: resposta normalizada produzida pelo adapter Salomao v1.
- `SupervisorDecision`: decisão final estruturada que o backend valida e aplica.
- `ActionIntent` / `HubSpotAction`: ações recomendadas e escritas no HubSpot.

## Modelos

### `AgentSession`

Sessão de conversa com agente.

### `AgentMemory`

Memória persistente por sessão.

### `AgentTrace`

Trace de execução por turno.

### `TokenTrackingLog`

Custo e consumo de tokens por execução.

## Lifecycle deterministico

- `ConversationInstance`: instancia persistida da state machine de atendimento.
- `ConversationEvent`: ledger append-only de eventos normalizados a partir de webhooks HubSpot.
- `ConversationStateTransition`: trilha auditavel de toda mudanca de estado.
- `AgentRun`: snapshot de execucao de agente/modelo com entrada, saida, tokens, latencia, custo e status.
- `ToolCallAuditLog`: auditoria de tools externas ou com efeito colateral.
- `EventNormalizer`: converte `WebhookEvent` bruto em evento interno canonico.
- `RoutingPolicyEngine`: roteia deterministicamente para `IGNORE`, `AUTO_ASSIGNMENT`, `AI_TRIAGE`, `HUMAN_HANDOFF`, `CLOSE` ou `WAIT_FOR_CONTACT_DATA`.
- `channel_capabilities`: aplica bloqueios configuráveis por canal; WhatsApp é sempre permitido para evitar que configurações legadas interrompam o atendimento.
- `tool_permissions`: aplica allowlist de tools por estado do lifecycle.
- `build_handoff_package`: monta contexto minimo para transferencia humana.
- `execution.apply_supervisor_result`: aplica respostas e handoffs com
  permissão por estado, idempotência e auditoria.
- `content_safety.assess_customer_content`: sanitiza conteúdo e bloqueia
  tentativas explícitas de sobrescrever instruções antes do LLM.
- `run_lifecycle_watchdog`: detecta instâncias presas e transiciona para
  `FAILED_RETRYABLE`; o dispatcher periódico reexecuta ou faz handoff seguro.

## Endpoints

Base: `/api/v1/ai/` (quando `AI_ROUTING_ENABLED=true`)

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| POST | `/chat/` | JWT | Chat legado com agente |
| POST | `/triage/` | JWT | Triagem com Heimdall |
| POST | `/salomao/chat` | JWT | Chat com Supervisor multi-agente |
| POST | `/webhooks/hubspot/ticket-change` | — | Webhook HubSpot → Supervisor *(router existe em `apps/ai_agents/api/webhooks.py`, mas **não está montado** em `core/urls.py`)* |

## Services principais

- `hydrate_ticket_context(ticket_id)`: expande payload mínimo do webhook em contexto completo do ticket.
- `hydrate_thread_context(thread_id)`: expande uma thread do HubSpot Conversations para contexto de IA.
- `build_salomao_prompt_from_hubspot_context(context)`: extrai a mensagem atual do cliente para eventos de conversa.
- `build_conversation_context_from_hubspot_context(context)`: normaliza contexto HubSpot para `ConversationContext`.
- `send_salomao_reply_to_hubspot_thread(context, text)`: envia a resposta para a thread do HubSpot.
- `request_human_handoff(...)`: persiste `HandoffPackage` e encaminha o ticket
  ao Matchmaker quando a ação está autorizada.
- `_run_supervisor_pipeline(ticket_id, is_off_hours)`: executa o pipeline desconectado do HTTP.
- `_record_usage(...)`: calcula custo e persiste `TokenTrackingLog`.

## Tasks Celery

- `run_supervisor_pipeline_task(ticket_id, is_off_hours)`: executa pipeline com lock Redis.
- `run_salomao_v1_thread_pipeline_task(thread_id)`: executa o Supervisor para HubSpot Conversations com lock Redis; o nome foi mantido por compatibilidade.
- `request_human_handoff_task(...)`: hidrata o contexto mínimo e cria handoff.
- `run_lifecycle_watchdog_task()`: detecta execuções presas.
- `retry_failed_lifecycle_instances_task()`: reexecuta falhas elegíveis e faz
  handoff quando o orçamento termina.

## Regras de negócio

- Heimdall sempre responde primeiro.
- Roteamento por `rota`:
  - `DUVIDAS_PLATAFORMA` / `ATENDIMENTO_IA` → RAG.
  - `BOLETO`, `MEIOS_DE_PAGAMENTO`, `FINANCEIRO`, `SUPORTE_TECNICO_N1`, `EVENTOS`, `CUSTOMER_SUCCESS` → Action.
  - `ESCALAR_IMEDIATAMENTE` → handoff humano.
- Prioridade `CRITICA` → handoff humano mesmo sem rota de escalation.
- Dados faltantes ou resposta candidata → `WAITING_FOR_CUSTOMER`.
- Resolução por IA só fecha após confirmação explícita do cliente.
- Tools externas exigem estado permitido, chave de idempotência e
  `ToolCallAuditLog`.
- Circuit breaker: > 15k tokens por sessão → bloqueio.
- Primeira mensagem: greeting obrigatório. Demais: não repetir.
- Quando `SALOMAO_V1_BASE_URL` estiver preenchido, `/api/v1/ai/salomao/chat` e eventos `conversation.newMessage` seguem pelo Supervisor; o Salomao v1 entra como membro `SalomaoChat`, nao como bypass direto.
- `/api/v1/ai/triage/` permanece dedicado ao Heimdall.
- Eventos de conversa com direcao `OUTGOING` sao ignorados para evitar que o Judah responda a propria mensagem.

## Arquivos relacionados

- [`apps/ai_agents/agents/base.py`](../../apps/ai_agents/agents/base.py)
- [`apps/ai_agents/agents/supervisor.py`](../../apps/ai_agents/agents/supervisor.py)
- [`apps/ai_agents/agents/triage.py`](../../apps/ai_agents/agents/triage.py)
- [`apps/ai_agents/agents/rag.py`](../../apps/ai_agents/agents/rag.py)
- [`apps/ai_agents/agents/action.py`](../../apps/ai_agents/agents/action.py)
- [`apps/ai_agents/agents/salomao_chat.py`](../../apps/ai_agents/agents/salomao_chat.py)
- [`apps/ai_agents/contracts.py`](../../apps/ai_agents/contracts.py)
- [`apps/ai_agents/api/routers.py`](../../apps/ai_agents/api/routers.py)
- [`apps/ai_agents/api/webhooks.py`](../../apps/ai_agents/api/webhooks.py)
- [`apps/ai_agents/tasks.py`](../../apps/ai_agents/tasks.py)
- [`apps/ai_agents/services/hubspot.py`](../../apps/ai_agents/services/hubspot.py)
- [`apps/integrations/salomao_v1/client.py`](../../apps/integrations/salomao_v1/client.py)
- [`apps/ai_agents/utils/pricing.py`](../../apps/ai_agents/utils/pricing.py)
- [`apps/ai_agents/mcp_servers/hubspot_server.py`](../../apps/ai_agents/mcp_servers/hubspot_server.py)

## Pontos de atenção

- `debug_mode=True` é passado via `getattr(settings, "DEBUG", False)` na base, mas o README alerta que alguns agentes podem ter `debug_mode=True` hardcoded (TODO: verificar).
- `run_pipeline_async` executa `run_pipeline` em thread pool, que por sua vez executa `Team.run` síncrono. MCP tools async podem não funcionar corretamente nesse cenário.
- O Supervisor muta `self._team.instructions` a cada requisição (risco H3 no README).
- O circuit breaker é acumulado por sessão, não janela rolante.

## Recomendações

- Remover `debug_mode=True` hardcoded antes da produção.
- Avaliar execução realmente async do Team quando houver MCP tools.
- Implementar janela rolante para o circuit breaker.
- Adicionar testes com mocks para LLM calls.
