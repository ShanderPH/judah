# Endpoints HTTP

## Resumo

Lista completa dos endpoints da API JUDAH por router. Status e schemas podem variar conforme evolução do código; sempre consulte `/api/v1/docs` para a versão atual.

## Contexto

Todos os endpoints estão sob `/api/v1/`. Endpoints marcados com `JWT` exigem header `Authorization: Bearer <access_token>`. Endpoints marcados com `—` são públicos.

---

## Auth (`/api/v1/auth/`)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| POST | `/register` | — | Cria novo usuário |
| POST | `/login` | — | Autentica e retorna tokens JWT |
| POST | `/refresh` | — | Gera novo access token a partir de refresh |
| POST | `/logout` | — | Invalida refresh token (blacklist) |
| GET | `/me` | JWT | Perfil do usuário logado |
| PATCH | `/me` | JWT | Atualiza perfil |
| POST | `/me/change-password` | JWT | Altera senha |
| GET | `/{user_id}` | JWT | Busca usuário por ID |

### Schemas

- `LoginRequest`: `username`, `password`
- `RegisterRequest`: `username`, `email`, `password`, `first_name`, `last_name`
- `TokenResponse`: `access`, `refresh`
- `UserResponse`: `id`, `username`, `email`, `first_name`, `last_name`, `role`, `avatar_url`, `is_ai_agent`
- `ChangePasswordRequest`: `current_password`, `new_password`

---

## Church (`/api/v1/church/`)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/` | JWT | Lista igrejas ativas (paginado) |
| GET | `/{church_id}` | JWT | Detalhe de uma igreja |

---

## Knowledge (`/api/v1/knowledge/`)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/articles/` | JWT | Lista artigos publicados |
| GET | `/articles/{slug}` | JWT | Detalhe de artigo |
| POST | `/search/` | — | Busca semântica |

### Schemas

- `SearchRequest`: `query`, `top_k` (default 5), `category_slug`
- `SearchResultItem`: `article_id`, `title`, `summary`, `score`, `url`

---

## Support (`/api/v1/support/`)

### Tickets

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/tickets/` | JWT | Lista tickets (filtros: status, church, priority) |
| POST | `/tickets/` | JWT | Cria ticket |
| GET | `/tickets/{ticket_id}` | JWT | Detalhe de ticket |
| PATCH | `/tickets/{ticket_id}` | JWT | Atualiza ticket |

### Fila

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/queue/status/` | JWT | Status da fila |
| GET | `/queue/pending/` | JWT | Conversas pendentes |
| GET | `/queue/assigned/` | JWT | Conversas atribuídas |
| GET | `/queue/health/` | JWT | Diagnóstico completo |
| POST | `/queue/sync-novo/` | — | Sincroniza tickets NOVO do HubSpot |
| GET | `/queue/metrics/` | JWT | Métricas de fila |

### Horário comercial

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/business-hours/` | — | Configuração atual |
| GET | `/special-schedules/` | — | Lista exceções |
| POST | `/special-schedules/` | — | Cria exceção |
| DELETE | `/special-schedules/{schedule_id}` | — | Remove exceção |

### Agentes (admin/manager)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/agents/` | JWT (manager+) | Lista agentes |
| GET | `/agents/{agent_id}` | JWT (manager+) | Detalhe de agente |
| POST | `/agents/` | JWT (manager+) | Cria agente |
| PATCH | `/agents/{agent_id}` | JWT (manager+) | Atualiza agente |
| POST | `/agents/{agent_id}/inactivate` | JWT (manager+) | Inativa agente |
| POST | `/agents/{agent_id}/reactivate` | JWT (manager+) | Reativa agente |
| GET | `/agents/{agent_id}/metrics/` | JWT (manager+) | Métricas do agente |
| GET | `/agents/{agent_id}/time-logs/` | JWT (manager+) | Logs de tempo |

### Atribuição manual

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| POST | `/queue/manual-assign/` | JWT (manager+) | Atribui ticket manualmente |
| POST | `/queue/force-reassign/` | JWT (manager+) | Reatribui ticket forçadamente |

### Métricas

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/metrics/agents/` | JWT (manager+) | Métricas de agentes |
| GET | `/metrics/agents/summary/` | JWT (manager+) | Resumo de métricas |
| GET | `/time-logs/` | JWT (manager+) | Logs de tempo |
| GET | `/reassignments/` | JWT (manager+) | Reatribuições |
| GET | `/reassignments/summary/` | JWT (manager+) | Resumo de reatribuições |

---

## Analytics (`/api/v1/analytics/`)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/reports/` | JWT | Lista relatórios diários |
| GET | `/reports/{report_date}` | JWT | Relatório por data |

---

## Webhooks (`/api/v1/webhooks/`)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| POST | `/hubspot/` | — | Recebe webhooks do HubSpot |
| POST | `/jira/` | — | Recebe webhooks do Jira |

---

## Health (`/api/v1/health/`)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| GET | `/` | — | Liveness probe |
| GET | `/ready` | — | Readiness probe |

---

## AI Agents (`/api/v1/ai/` — condicional)

| Método | Path | Auth | Resumo |
|--------|------|------|--------|
| POST | `/chat/` | JWT | Chat legado |
| POST | `/triage/` | JWT | Triagem com Heimdall |
| POST | `/salomao/chat` | JWT | Chat com Supervisor |
| POST | `/webhooks/hubspot/ticket-change` | — | Webhook HubSpot → Supervisor |

---

## Arquivos relacionados

- [`apps/auth_user/api.py`](../../apps/auth_user/api.py)
- [`apps/church/api.py`](../../apps/church/api.py)
- [`apps/knowledge/api.py`](../../apps/knowledge/api.py)
- [`apps/support/api.py`](../../apps/support/api.py)
- [`apps/support/admin_api.py`](../../apps/support/admin_api.py)
- [`apps/analytics/api.py`](../../apps/analytics/api.py)
- [`apps/webhooks/api.py`](../../apps/webhooks/api.py)
- [`apps/health/api.py`](../../apps/health/api.py)
- [`apps/ai_agents/api.py`](../../apps/ai_agents/api.py)
- [`apps/ai_agents/api/routers.py`](../../apps/ai_agents/api/routers.py)
- [`apps/ai_agents/api/webhooks.py`](../../apps/ai_agents/api/webhooks.py)
- [`core/urls.py`](../../core/urls.py)

## Pontos de atenção

- O router de IA só existe quando `AI_ROUTING_ENABLED=true`.
- Alguns endpoints de support exigem role `manager` ou `admin` via `require_manager_or_admin`.
- A busca semântica é pública (`auth=None`), o que pode expor conteúdo da base de conhecimento.

## Recomendações

- Adicionar rate limit nos endpoints públicos.
- Revisar necessidade de `auth=None` em `/knowledge/search/`.
- Manter esta lista sincronizada com o código.
