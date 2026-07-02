# Decisões Técnicas

## Resumo

Registro das principais decisões arquiteturais e de implementação encontradas na codebase. Cada decisão inclui o contexto, a escolha feita, a justificativa e os arquivos relacionados.

## Contexto

Decisões técnicas estão espalhadas por docstrings, comentários e código. Este documento as consolida para facilitar o onboarding e revisões futuras.

## ADRs

### ADR-001: Django + Django Ninja em vez de DRF

- **Contexto:** necessidade de API rápida, tipada e com documentação OpenAPI automática.
- **Decisão:** usar Django 5.2 LTS com Django Ninja 1.6.
- **Justificativa:** Ninja oferece schemas Pydantic nativos, menor boilerplate que DRF e geração automática de docs.
- **Consequências:** autenticação usa `django-ninja-jwt` ao invés de `djangorestframework-simplejwt`.
- **Arquivos:** [`core/urls.py`](../../core/urls.py), [`apps/auth_user/api.py`](../../apps/auth_user/api.py).

### ADR-002: Agno `Team` no modo `coordinate` para Salomão

- **Contexto:** orquestrar triagem, RAG e ações externas em um único ponto de entrada.
- **Decisão:** `SalomaoSupervisorAgent` monta um `agno.team.Team` com `TeamMode.coordinate`.
- **Justificativa:** o Team atua como "maestro LLM", decide quais membros acionar e sintetiza a resposta.
- **Consequências:** o Supervisor não herda de `BaseInChurchAgent`; é um wrapper. Sub-agentes compartilham o mesmo `session_id` e RedisDb.
- **Arquivos:** [`apps/ai_agents/agents/supervisor.py`](../../apps/ai_agents/agents/supervisor.py).

### ADR-003: Agente Heimdall com `output_schema` estruturado

- **Contexto:** replicar o contrato JSON do fluxo N8N legado.
- **Decisão:** `HeimdallTriageAgent` usa `output_schema=TriageResult` e `structured_outputs=True`.
- **Justificativa:** força o LLM a devolver `rota`, `prioridade`, `tags`, `dados_faltantes`, `sentimento` em formato Pydantic validado.
- **Arquivos:** [`apps/ai_agents/agents/triage.py`](../../apps/ai_agents/agents/triage.py).

### ADR-004: MCP via FastMCP stdio para HubSpot

- **Contexto:** desacoplar o agente de ações do código das chamadas HubSpot.
- **Decisão:** servidor MCP `hubspot_server.py` roda como subprocesso stdio e expõe `get_ticket_status`, `create_helpdesk_ticket`, `update_ticket`.
- **Justificativa:** permite adicionar ferramentas sem alterar o agente; segue o protocolo MCP.
- **Consequências:** o processo filho herda o environment do pai; secrets devem ser auditados.
- **Arquivos:** [`apps/ai_agents/mcp_servers/hubspot_server.py`](../../apps/ai_agents/mcp_servers/hubspot_server.py), [`apps/ai_agents/agents/action.py`](../../apps/ai_agents/agents/action.py).

### ADR-005: Feature flag `AI_ROUTING_ENABLED`

- **Contexto:** a funcionalidade de IA ainda está em validação; não pode impactar o legado.
- **Decisão:** o router `/api/v1/ai/` só é montado quando `AI_ROUTING_ENABLED=true`.
- **Justificativa:** isola código de IA, evita carregar dependências (Agno, Pinecone, MCP) quando desnecessário e protege o sistema legado.
- **Arquivos:** [`core/urls.py`](../../core/urls.py), [`core/settings/base.py`](../../core/settings/base.py).

### ADR-006: PostgreSQL + Supabase

- **Contexto:** banco relacional transacional; dados históricos vêm do HelpdeskDB.
- **Decisão:** PostgreSQL 16 hospedado no Supabase.
- **Justificativa:** compatibilidade com tabelas legadas (`webhook_events`, `kb_articles`, `agents`, `tickets`), suporte a JSONB, conexões gerenciadas.
- **Consequências:** settings usam `dj_database_url` para parsear `DATABASE_URL`.
- **Arquivos:** [`core/settings/base.py`](../../core/settings/base.py).

### ADR-007: Redis como cache, broker e session store de IA

- **Contexto:** necessidade de cache, broker Celery e persistência de sessão dos agentes.
- **Decisão:** Redis 7 unificado para todas as funções.
- **Justificativa:** simplifica infraestrutura; session store Agno usa prefixo `inchurch:agent:{session_id}`.
- **Arquivos:** [`core/settings/base.py`](../../core/settings/base.py), [`apps/ai_agents/agents/base.py`](../../apps/ai_agents/agents/base.py).

### ADR-008: Auto-atribuição com Matchmaker + SAT

- **Contexto:** substituir atribuição manual de tickets por atribuição automática baseada em disponibilidade.
- **Decisão:** SAT faz heartbeat de 20s buscando availability no HubSpot; Matchmaker consome a fila `new_conversations`.
- **Justificativa:** reduz latência de atribuição e mantém contadores locais sincronizados com HubSpot.
- **Arquivos:** [`apps/support/sat_service.py`](../../apps/support/sat_service.py), [`apps/support/matchmaker_service.py`](../../apps/support/matchmaker_service.py).

### ADR-009: Webhooks HubSpot validados por HMAC v1/v3

- **Contexto:** receber eventos do HubSpot de forma segura.
- **Decisão:** suportar v1 (SHA-256) e v3 (HMAC-SHA256) e rejeitar em produção se secret não estiver configurado.
- **Justificativa:** cobre diferentes versões de private apps do HubSpot.
- **Consequências:** em `DEBUG` sem secret, a verificação é bypassada (risco de segurança).
- **Arquivos:** [`apps/webhooks/api.py`](../../apps/webhooks/api.py), [`apps/ai_agents/api/webhooks.py`](../../apps/ai_agents/api/webhooks.py).

### ADR-010: Logs estruturados com structlog

- **Contexto:** necessidade de logs correlacionados por request_id e compatíveis com agregadores.
- **Decisão:** structlog com `JSONRenderer` em produção e `ConsoleRenderer` em desenvolvimento.
- **Justificativa:** facilita debug e monitoramento; PII é scrubbed por processador customizado.
- **Arquivos:** [`common/logging.py`](../../common/logging.py), [`common/middleware.py`](../../common/middleware.py).

## Pontos de atenção

- Algumas decisões ainda estão em transição (ex: `asyncio.create_task` do webhook legado foi migrado para Celery, mas a task ainda executa async internamente).
- O fallback de LLM para GPT-4o-mini é o mesmo modelo da triagem; se houver rate-limit generalizado, o fallback também pode falhar.
- A feature flag de IA é global; não há granularidade por tenant/igreja.

## Recomendações

- Revisar ADRs a cada release.
- Documentar novas decisões neste arquivo assim que forem tomadas.
- Considerar um ADR sobre estratégia de testes de agentes de IA.
