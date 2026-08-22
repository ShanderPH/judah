# Variáveis de ambiente

Use `.env` apenas localmente e nunca versione segredos. A fonte normativa dos
nomes e defaults é `core/settings/`.

## Infraestrutura

- `DJANGO_SECRET_KEY`, `DJANGO_ENV`, `DJANGO_ALLOWED_HOSTS`
- `DATABASE_URL`, `JUDAH_SCHEMA_DATABASE_URL`
- `REDIS_URL` ou `REDIS_PRIVATE_URL`
- `CELERY_REDIS_MAX_CONNECTIONS`, `REDIS_CACHE_MAX_CONNECTIONS`

## Operação do Help Desk

- `AUTO_ASSIGNMENT_ENABLED`, `AUTO_ASSIGNMENT_CANARY_AGENT_IDS`
- `AVAILABILITY_AUTHORITY_ENVIRONMENT`
- `ABSENCE_SAFE_ELIGIBILITY_SHADOW`, `ABSENCE_SAFE_ELIGIBILITY_ENFORCED`
- `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_APP_SECRET`, `HUBSPOT_PORTAL_ID`
- `HUBSPOT_SUPPORT_PIPELINE_ID`, `HUBSPOT_SUPPORT_NEW_STAGE_ID`
- `HUBSPOT_SUPPORT_CLOSED_STAGE_ID`, `HUBSPOT_N1_TEAM_ID`
- IDs dos pipelines operacionais default e N2 declarados em settings

## Integrações preservadas

- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_HOST`
- `SALOMAO_V1_BASE_URL`, timeouts e máximo de tentativas
- `JIRA_SERVER_URL`, `JIRA_API_TOKEN`, `JIRA_USER_EMAIL`, `JIRA_WEBHOOK_SECRET`
- `SENTRY_DSN`

Não existem variáveis ativas de identificação, Heimdall, Supervisor, pipeline de
triagem, rollout de bot ou reconciliação de mensagens.
