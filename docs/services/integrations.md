# `apps.integrations` — Integrações Externas

## Resumo

Módulo de clients tipados para sistemas externos. Cada integração tem seu próprio subpacote com client, schemas e services.

## Contexto

Os clients são singletons lazy-initialized e usam circuit breaker (`common/circuit_breaker.py`) para proteger chamadas externas.

## Submódulos

### `apps.integrations.hubspot`

- **Client:** `HubSpotClient` em [`client.py`](../../apps/integrations/hubspot/client.py).
- **Services:** `sync_ticket_to_hubspot`.
- **Schemas:** `HubSpotTicketSchema`, `HubSpotContactSchema`.
- **Constantes:**
  - Pipeline de suporte: `636459134`.
  - Stage NOVO: `939275049`.
  - Stage FECHADO: `939275052`.
  - Time N1: `8`.
- **Métodos principais:**
  - `get_ticket`, `get_ticket_details`
  - `create_ticket`, `assign_ticket_owner`
  - `search_contact_by_email`, `get_contact_by_id`
  - `get_team_members`, `get_owner_details`
  - `search_tickets_in_novo_stage`
  - `get_all_owners_availability`
  - `count_active_tickets_by_owner`

### `apps.integrations.jira`

- **Client:** `JiraClient` em [`client.py`](../../apps/integrations/jira/client.py).
- **Services:** `escalate_ticket_to_jira`.
- **Schemas:** `JiraIssueSchema`, `CreateJiraIssueRequest`.
- **Métodos principais:**
  - `search_issues`
  - `create_issue`

### `apps.integrations.pinecone_client`

- **Client:** `PineconeClient` em [`client.py`](../../apps/integrations/pinecone_client/client.py).
- **Métodos principais:**
  - `upsert`
  - `search` (faz embedding via OpenAI)
  - `delete`

### `apps.integrations.supabase_client`

- **Client:** `get_supabase_client()` em [`client.py`](../../apps/integrations/supabase_client/client.py).
- Uso: acesso ao PostgreSQL/REST do Supabase. **TODO: confirmar** onde é usado ativamente; o banco principal é acessado via Django ORM.

## Regras de negócio

- HubSpotClient é singleton; recriação só ocorre se `_hubspot_client` for None.
- Chamadas ao HubSpot usam circuit breaker com 5 falhas e 60s de recovery.
- `count_active_tickets_by_owner` retorna `-1` em erro; chamadores devem tratar.

## Arquivos relacionados

- [`apps/integrations/hubspot/client.py`](../../apps/integrations/hubspot/client.py)
- [`apps/integrations/jira/client.py`](../../apps/integrations/jira/client.py)
- [`apps/integrations/pinecone_client/client.py`](../../apps/integrations/pinecone_client/client.py)
- [`apps/integrations/supabase_client/client.py`](../../apps/integrations/supabase_client/client.py)
- [`common/circuit_breaker.py`](../../common/circuit_breaker.py)

## Pontos de atenção

- `_hubspot_client` é global; não há mecanismo de reset em caso de troca de token em runtime.
- `PineconeClient.search` cria um cliente OpenAI a cada chamada.
- O uso do Supabase client não é evidente na codebase analisada.

## Recomendações

- Adicionar retry com backoff nos clients.
- Cachear cliente OpenAI no PineconeClient.
- Documentar claramente o uso do Supabase client ou removê-lo se não for necessário.
