# `apps.ai_agents` — Agentes de IA

## Resumo

Módulo do ecossistema **Salomão**: agentes de IA para atendimento ao cliente, composto por triagem (Heimdall), respostas baseadas em conhecimento (RAG) e ações externas (HelpdeskAction via MCP).

## Contexto

O módulo é opcional e controlado pela feature flag `AI_ROUTING_ENABLED`. Quando desabilitado, o router `/api/v1/ai/` não é montado e as dependências (Agno, Pinecone, MCP) não são carregadas.

## Responsabilidades

- Orquestrar o Supervisor multi-agente.
- Classificar mensagens (Heimdall).
- Responder dúvidas via RAG (Pinecone).
- Executar ações no HubSpot/Jira via MCP.
- Persistir sessões, memórias, traces e custos.
- Receber webhooks do HubSpot e executar pipeline assíncrono.
- Expor o Salomao v1 externo como membro interno do Supervisor quando `SALOMAO_V1_BASE_URL` estiver configurado.

## Agentes

### `HeimdallTriageAgent`

- Modelo: `DEFAULT_MINI_MODEL` (gpt-4o-mini).
- Saída estruturada: `TriageResult` (rota, prioridade, tags, dados_faltantes, sentimento).
- Sem histórico.

### `KnowledgeRagAgent`

- Modelo: `DEFAULT_MODEL` (gpt-4o).
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
- Disponivel somente quando `SALOMAO_V1_BASE_URL` e `SALOMAO_V1_AS_TEAM_AGENT=true`.
- Saida normalizada: `SalomaoChatDraft`.
- Em erro de provider, devolve draft seguro com handoff humano sem vazar tokens, chaves ou stack traces.

### `SalomaoSupervisorAgent`

- Wrapper sobre `agno.team.Team` modo `coordinate`.
- Orquestra Heimdall -> RAG/Action/SalomaoChat.
- Implementa circuit breaker e greeting injection.
- Saída: `SalomaoResponse`.

### `SalomaoDirectAgent` (legacy)

- Agente único para smoke tests.

## Modelos

### `AgentSession`

Sessão de conversa com agente.

### `AgentMemory`

Memória persistente por sessão.

### `AgentTrace`

Trace de execução por turno.

### `TokenTrackingLog`

Custo e consumo de tokens por execução.

## Endpoints

Base: `/api/v1/ai/` (quando `AI_ROUTING_ENABLED=true`)

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| POST | `/chat/` | JWT | Chat legado com agente |
| POST | `/triage/` | JWT | Triagem com Heimdall |
| POST | `/salomao/chat` | JWT | Chat com Supervisor multi-agente |
| POST | `/webhooks/hubspot/ticket-change` | — | Webhook HubSpot → Supervisor |

## Services principais

- `hydrate_ticket_context(ticket_id)`: expande payload mínimo do webhook em contexto completo do ticket.
- `hydrate_thread_context(thread_id)`: expande uma thread do HubSpot Conversations para contexto de IA.
- `build_salomao_prompt_from_hubspot_context(context)`: extrai a mensagem atual do cliente para eventos de conversa.
- `build_conversation_context_from_hubspot_context(context)`: normaliza contexto HubSpot para `ConversationContext`.
- `send_salomao_reply_to_hubspot_thread(context, text)`: envia a resposta para a thread do HubSpot.
- `_run_supervisor_pipeline(ticket_id, is_off_hours)`: executa o pipeline desconectado do HTTP.
- `_record_usage(...)`: calcula custo e persiste `TokenTrackingLog`.

## Tasks Celery

- `run_supervisor_pipeline_task(ticket_id, is_off_hours)`: executa pipeline com lock Redis.
- `run_salomao_v1_thread_pipeline_task(thread_id)`: executa o Supervisor para HubSpot Conversations com lock Redis; o nome foi mantido por compatibilidade.

## Regras de negócio

- Heimdall sempre responde primeiro.
- Roteamento por `rota`:
  - `DUVIDAS_PLATAFORMA` / `ATENDIMENTO_IA` → RAG.
  - `BOLETO`, `MEIOS_DE_PAGAMENTO`, `FINANCEIRO`, `SUPORTE_TECNICO_N1`, `EVENTOS`, `CUSTOMER_SUCCESS` → Action.
  - `ESCALAR_IMEDIATAMENTE` → handoff humano.
- Prioridade `CRITICA` → handoff humano mesmo sem rota de escalation.
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
