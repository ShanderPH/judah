# Variáveis de Ambiente

## Resumo

Lista completa das variáveis de ambiente usadas pelo JUDAH, com indicação de obrigatoriedade, valor padrão e propósito.

## Contexto

As configurações são carregadas via `python-decouple` nos arquivos de settings do Django. Secrets nunca devem ser commitados no repositório.

## Variáveis obrigatórias

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `DJANGO_SECRET_KEY` | `core/settings/base.py` | Chave secreta do Django. Também usada como signing key JWT (HS256). |
| `DATABASE_URL` | `core/settings/base.py` | URL de conexão com PostgreSQL. |
| `REDIS_URL` | `core/settings/base.py` | URL do Redis (cache, broker Celery, session store). |

## Variáveis de IA

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `OPENAI_API_KEY` | `apps/ai_agents/agents/base.py` | Chave da OpenAI para GPT-4o / GPT-4o-mini. |
| `ANTHROPIC_API_KEY` | `apps/ai_agents/agents/base.py` | Fallback opcional para modelos Anthropic. |
| `DEFAULT_MODEL` | `apps/ai_agents/agents/base.py` | Modelo principal (padrão: `gpt-4o`). |
| `DEFAULT_MINI_MODEL` | `apps/ai_agents/agents/base.py` | Modelo compacto (padrão: `gpt-4o-mini`). |
| `PINECONE_API_KEY` | `apps/integrations/pinecone_client/client.py` | Chave da API Pinecone. |
| `PINECONE_INDEX_NAME` | `apps/ai_agents/agents/rag.py` | Nome do índice Pinecone (padrão: `inchurch-knowledge`). |
| `PINECONE_HOST` | `apps/ai_agents/agents/rag.py` | URL do data-plane do Pinecone (evita adivinhar cloud/region). |
| `PINECONE_CLOUD` | `apps/ai_agents/agents/rag.py` | Cloud do Pinecone (padrão: `aws`). |
| `PINECONE_REGION` | `apps/ai_agents/agents/rag.py` | Região do Pinecone (padrão: `us-east-1`). |
| `PINECONE_DIMENSION` | `apps/ai_agents/agents/rag.py` | Dimensão do embedding (padrão: `1536`). |
| `EMBEDDING_MODEL` | `apps/ai_agents/agents/rag.py` | Modelo de embedding (padrão: `text-embedding-ada-002`). |
| `AGNO_TELEMETRY` | Ambiente | Desabilita telemetria do Agno. |
| `SALOMAO_V1_BASE_URL` | `apps/integrations/salomao_v1/client.py` | URL base do servico standalone Salomao v1. Quando preenchida, Judah chama `POST /chat` neste servico. |
| `SALOMAO_V1_TIMEOUT_SECONDS` | `apps/integrations/salomao_v1/client.py` | Timeout HTTP da bridge Salomao v1 (padrao: `45`). |

## Variáveis de HubSpot

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `HUBSPOT_ACCESS_TOKEN` | `apps/integrations/hubspot/client.py` | Token OAuth de private app. |
| `HUBSPOT_APP_SECRET` | `apps/webhooks/api.py`, `apps/ai_agents/api/webhooks.py` | Secret para validar assinatura HMAC v1/v3 dos webhooks. |
| `HUBSPOT_PORTAL_ID` | `apps/ai_agents/mcp_servers/hubspot_server.py` | Portal ID para construir URLs de ticket. |
| `HUBSPOT_N1_TEAM_ID` | `core/settings/base.py` | ID do time N1 de suporte (padrão: `8`). |
| `USE_MOCK_HUBSPOT` | `apps/ai_agents/services/hubspot.py` | Modo mock para simulador local (dev only). |
| `HUBSPOT_SALOMAO_SENDER_ACTOR_ID` | `apps/ai_agents/services/hubspot.py` | Actor ID usado para postar respostas do Salomao v1 em threads do HubSpot. |

## Variáveis de Jira

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `JIRA_SERVER_URL` | `apps/integrations/jira/client.py` | URL do servidor Jira. |
| `JIRA_API_TOKEN` | `apps/integrations/jira/client.py` | Token de API do Jira. |
| `JIRA_USER_EMAIL` | `apps/integrations/jira/client.py` | Email do usuário Jira. |
| `JIRA_WEBHOOK_SECRET` | `apps/webhooks/api.py` | Secret para validar webhooks do Jira. |

## Variáveis de Supabase

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `SUPABASE_URL` | `apps/integrations/supabase_client/client.py` | URL do projeto Supabase. |
| `SUPABASE_SERVICE_KEY` | `apps/integrations/supabase_client/client.py` | Service role key do Supabase. |

## Variáveis de segurança e configuração geral

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `DJANGO_ENV` | `core/settings/base.py`, `core/settings/production.py` | Ambiente: `development`, `staging`, `production`, `test`. |
| `DJANGO_DEBUG` | `core/settings/base.py` | Ativa modo debug (padrão: `False`). |
| `DJANGO_ALLOWED_HOSTS` | `core/settings/base.py` | Hosts permitidos (separados por vírgula). |
| `CORS_ALLOWED_ORIGINS` | `core/settings/base.py` | Origens permitidas para CORS. |
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` | `core/settings/base.py` | TTL do access token JWT (padrão: `60`). |
| `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | `core/settings/base.py` | TTL do refresh token JWT (padrão: `7`). |
| `AI_ROUTING_ENABLED` | `core/settings/base.py`, `core/urls.py` | Habilita router de IA (padrão: `False`). |

## Variáveis de observabilidade

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `SENTRY_DSN` | `core/settings/base.py` | DSN do Sentry. |
| `SENTRY_TRACES_SAMPLE_RATE` | `core/settings/base.py` | Taxa de amostragem de traces (padrão: `0.05`). |
| `SENTRY_PROFILES_SAMPLE_RATE` | `core/settings/base.py` | Taxa de profiling (padrão: `0.01`). |
| `GIT_SHA` | `core/settings/base.py` | SHA do release para o Sentry. |

## Variáveis internas adicionais

| Variável | Onde é usada | Descrição |
|----------|--------------|-----------|
| `INRADAR_AUTH_TOKEN` | `apps/ai_agents/tools/inchurch_tools.py` | Token para API interna InRadar (diagnóstico de eventos). |
| `REDIS_PRIVATE_URL` | `core/settings/base.py` | Fallback para `REDIS_URL` (usado pelo Railway). |
| `RAILWAY_PUBLIC_DOMAIN` | `core/settings/production.py` | Injetado pelo Railway em `ALLOWED_HOSTS`. |

## Exemplo de `.env` para desenvolvimento

```bash
DJANGO_ENV=development
DJANGO_SECRET_KEY=dev-secret-key-change-me
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

DATABASE_URL=postgresql://judah:judah_dev_password@localhost:5432/judah_dev
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=your-service-key

REDIS_URL=redis://localhost:6379/0

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
PINECONE_API_KEY=your-pinecone-key
PINECONE_INDEX_NAME=inchurch-knowledge
SALOMAO_V1_BASE_URL=http://localhost:8001
SALOMAO_V1_TIMEOUT_SECONDS=45

HUBSPOT_ACCESS_TOKEN=your-hubspot-token
HUBSPOT_APP_SECRET=your-app-secret
HUBSPOT_PORTAL_ID=your-portal-id
HUBSPOT_SALOMAO_SENDER_ACTOR_ID=A-123456

JIRA_SERVER_URL=https://inchurch.atlassian.net
JIRA_API_TOKEN=your-jira-token
JIRA_USER_EMAIL=your-email@inchurch.com.br

SENTRY_DSN=https://xxxx@sentry.io/xxxx

CORS_ALLOWED_ORIGINS=http://localhost:3000,https://app.inchurch.com.br

JWT_ACCESS_TOKEN_LIFETIME_MINUTES=60
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

AI_ROUTING_ENABLED=false
```

## Arquivos relacionados

- [`.env.example`](../../.env.example): template oficial.
- [`core/settings/base.py`](../../core/settings/base.py): carregamento das variáveis.

## Pontos de atenção

- `HUBSPOT_APP_SECRET` deve estar preenchido em produção; em `DEBUG` vazio, a assinatura é bypassada.
- `DJANGO_SECRET_KEY` é usada tanto pelo Django quanto pelo JWT; rotação invalida todas as sessões.
- `AI_ROUTING_ENABLED=false` desmonta o router `/api/v1/ai/` por completo.

## Recomendações

- Use um gerenciador de secrets (Railway, Antigravity Customizations) em produção.
- Nunca commit `.env` ou `.env.local`.
- Mantenha `.env.example` atualizado quando adicionar novas variáveis.
