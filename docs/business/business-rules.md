# Regras de Negócio

## Resumo

Regras explícitas e implícitas identificadas na codebase do JUDAH. Regras deduzidas estão marcadas como `Inferência baseada no código`.

## Contexto

As regras estão distribuídas entre models, services, agentes de IA e tasks Celery. Este documento as organiza por domínio.

## 1. Autenticação e usuários

### RBAC

- Usuários possuem um dos papéis: `admin`, `manager`, `agent`, `viewer`.
- Apenas `admin` e `manager` podem criar/editar agentes de suporte.
- `viewer` tem acesso de leitura (inferência baseada no nome da role).

### Login

- Login pode ser feito por `username` ou `email` (case-insensitive via `iexact`).
- Senha deve ter no mínimo 8 caracteres, pelo menos 1 letra e 1 dígito.
- JWT é HS256 e usa `DJANGO_SECRET_KEY` como signing key.
- Refresh tokens são rotacionados e blacklisted após uso.

### Arquivos relacionados

- [`apps/auth_user/models.py`](../../apps/auth_user/models.py)
- [`apps/auth_user/services.py`](../../apps/auth_user/services.py)
- [`apps/auth_user/schemas.py`](../../apps/auth_user/schemas.py)

## 2. Igrejas e planos

- Igreja (`Church`) é o cliente InChurch.
- Cada igreja pode ter um `Plan` e um `Gateway` (pagamento).
- Apenas igrejas `is_active=True` são listadas publicamente.
- `external_id` e `hubspot_company_id` são únicos/indexados.

### Arquivos relacionados

- [`apps/church/models.py`](../../apps/church/models.py)
- [`apps/church/services.py`](../../apps/church/services.py)

## 3. Base de conhecimento

- Artigos são sincronizados do HubSpot CMS.
- Artigos têm estado (`state`); apenas `PUBLISHED` são listados publicamente.
- Busca semântica é feita via Pinecone; artigos no Postgres guardam metadados.
- Cada `ArticleChunk` pertence a um `Article` e tem `chunk_index` único por artigo.

### Arquivos relacionados

- [`apps/knowledge/models.py`](../../apps/knowledge/models.py)
- [`apps/knowledge/services.py`](../../apps/knowledge/services.py)

## 4. Tickets e suporte

### Ticket

- `Ticket` mapeia a tabela legada `tickets`.
- Campos como `priority`, `status`, `ticket_church` são textos livres (não há `TextChoices`).
- `created_at` é obrigatório no modelo.

### Auto-atribuição

Um ticket só é elegível para auto-atribuição se:

1. Pertencer ao pipeline `636459134`.
2. Não tiver `hubspot_owner_id` preenchido.

Um agente só é elegível para receber ticket se:

1. `status_enum == ONLINE`.
2. `auto_assign_enabled == True`.
3. `is_active != False`.
4. `current_simultaneous_chats < max_simultaneous_chats`.

### Algoritmo de seleção de agente (4 regras)

1. **Online:** apenas agentes online.
2. **Evitar repetição:** não atribuir dois tickets consecutivos ao mesmo agente, a menos que seja o único online.
3. **Maior tempo ocioso:** preferir agente com `last_assignment_at` mais antigo (NULL = maior prioridade).
4. **Menor carga:** entre agentes igualmente elegíveis, preferir o com menos chats atuais.

### Fila

- `NewConversation` representa ticket aguardando atribuição.
- Ordem FIFO por `entered_queue_at`.
- `queue_position` é calculada dinamicamente (1-indexada).

### Fechamento

- Quando um ticket entra no stage `939275052` (FECHADO), o contador do agente atribuído é decrementado.
- Fechamentos são idempotentes via Redis lock.
- Handle time = `closed_at - assigned_at`.
- Resolution time = `closed_at - entered_queue_at`.

### Reatribuição manual/forçada

- Decrementa contador do agente anterior.
- Incrementa contador do novo agente.
- Registra `ConversationReassignment`.

### Horário comercial

- Segunda a sexta: 09h às 18h.
- Sábado: 09h às 13h.
- Domingo: 08h às 12h.
- Feriados e "Quinta Fire" (quinta 12h-13h) estão fora do horário.
- `BusinessHoursConfig` e `SpecialSchedule` podem sobrescrever essas regras.

### Arquivos relacionados

- [`apps/support/models.py`](../../apps/support/models.py)
- [`apps/support/queue_service.py`](../../apps/support/queue_service.py)
- [`apps/support/auto_assign_service.py`](../../apps/support/auto_assign_service.py)
- [`apps/support/matchmaker_service.py`](../../apps/support/matchmaker_service.py)
- [`apps/support/agent_sync_service.py`](../../apps/support/agent_sync_service.py)
- [`apps/ai_agents/utils/business_rules.py`](../../apps/ai_agents/utils/business_rules.py)

## 5. Agentes de IA

### Roteamento

- Heimdall classifica a mensagem em `rota` e `prioridade`.
- Supervisor delega para:
  - `KnowledgeRagAgent`: rotas `DUVIDAS_PLATAFORMA`, `ATENDIMENTO_IA`.
  - `HelpdeskActionAgent`: rotas `BOLETO`, `MEIOS_DE_PAGAMENTO`, `FINANCEIRO`, `SUPORTE_TECNICO_N1`, `EVENTOS`, `CUSTOMER_SUCCESS`.
  - Handoff humano: `ESCALAR_IMEDIATAMENTE`.

### Prioridade crítica

- Se `prioridade == CRITICA`, sinaliza transbordo humano mesmo que a rota não seja `ESCALAR_IMEDIATAMENTE`.

### Circuit breaker

- Se a sessão acumulou mais de 15.000 tokens, novas mensagens são bloqueadas com handoff.

### Greeting

- A primeira mensagem da sessão deve começar com a apresentação obrigatória do Salomão.
- Nas mensagens subsequentes, não repetir a apresentação.

### RAG

- Sempre buscar na base de conhecimento antes de responder.
- Se não encontrar, encerrar resposta com tag `<REQUIRES_ESCALATION>`.
- Citar fontes no formato: `Fonte: [Título] (ID: [article_id])`.

### Action Agent

- Sempre que possível, fechar o loop atualizando o ticket no HubSpot via `hubspot_update_ticket`.
- Informar o protocolo (ticket_id) ao usuário.
- Em off-hours, mover para `HUBSPOT_HUMAN_ESCALATION_STAGE_ID` dentro de `HUBSPOT_AI_TRIAGE_PIPELINE_ID`.

### Arquivos relacionados

- [`apps/ai_agents/agents/supervisor.py`](../../apps/ai_agents/agents/supervisor.py)
- [`apps/ai_agents/agents/triage.py`](../../apps/ai_agents/agents/triage.py)
- [`apps/ai_agents/agents/rag.py`](../../apps/ai_agents/agents/rag.py)
- [`apps/ai_agents/agents/action.py`](../../apps/ai_agents/agents/action.py)

## 6. Webhooks

- HubSpot webhooks são validados por HMAC v1 ou v3.
- Eventos são sempre persistidos em `WebhookEvent`.
- Em produção, sem `HUBSPOT_APP_SECRET`, a requisição é rejeitada.
- Eventos desconhecidos são marcados como processados mas logados.
- Após 3 retries, eventos vão para `DeadLetterQueue`.

### Arquivos relacionados

- [`apps/webhooks/api.py`](../../apps/webhooks/api.py)
- [`apps/webhooks/services.py`](../../apps/webhooks/services.py)

## 7. Analytics

- Métricas de fila são agregadas diariamente às 00:05.
- Métricas por agente são agregadas diariamente às 00:10.
- Fila é FIFO e o tempo de espera é calculado desde `entered_queue_at`.

### Arquivos relacionados

- [`apps/support/tasks.py`](../../apps/support/tasks.py)
- [`apps/analytics/tasks.py`](../../apps/analytics/tasks.py)

## Pontos de atenção

- O status do ticket em `apps.support.models.Ticket` é texto livre; não há enum. Isso pode levar a inconsistências.
- O horário comercial está hardcoded em `apps/ai_agents/utils/business_rules.py` e sobrescrito por `BusinessHoursConfig` em `apps/support`.
- A regra do circuit breaker de 15k tokens é acumulada por sessão, mas não é uma janela rolante (conforme risco documentado no README).

## Recomendações

- Padronizar `Ticket.status` e `Ticket.priority` para enums.
- Implementar janela rolante para o circuit breaker.
- Documentar o contrato de `BusinessHoursConfig` vs `SpecialSchedule` com exemplos.
