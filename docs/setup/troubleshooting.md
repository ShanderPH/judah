# Troubleshooting

## Resumo

Problemas comuns encontrados durante o desenvolvimento local, deploy e operação do JUDAH, com causas prováveis e soluções.

## Contexto

A codebase é complexa (Django + Celery + Redis + Postgres + IA + webhooks). Este documento acelera o diagnóstico de erros recorrentes.

## Problemas de setup

### `ModuleNotFoundError` ou `SyntaxError` ao rodar o projeto

**Causa provável:** Python diferente de 3.14, ou `run.ps1 agentos` apontando para `apps.ai_agents.agent_os:app`, que não existe.

**Solução:**

```bash
python --version  # deve ser 3.14.x
```

Use pyenv ou o instalador oficial para garantir a versão exata. O target `agentos` do `run.ps1` está quebrado; não use até que `apps/ai_agents/agent_os.py` seja criado.

### `django.core.exceptions.ImproperlyConfigured: SECRET_KEY must not be empty`

**Causa provável:** `.env` não existe ou `DJANGO_SECRET_KEY` não está definida.

**Solução:**

```bash
cp .env.example .env
# edite DJANGO_SECRET_KEY
```

### `psycopg.OperationalError: connection refused`

**Causa provável:** PostgreSQL não está rodando ou `DATABASE_URL` está incorreta.

**Solução:**

- Se usar Docker: `make docker-up` e aguarde o healthcheck.
- Se usar Postgres local: verifique se o serviço está ativo e se a porta é `5432`.

### `RedisError` ou timeout no cache

**Causa provável:** Redis não está rodando ou `REDIS_URL` está incorreta.

**Solução:**

```bash
redis-cli ping  # deve retornar PONG
```

## Problemas de autenticação

### Login retorna 401 mesmo com credenciais corretas

**Causa provável:**

- Tabela `token_blacklist_outstandingtoken` não foi migrada.
- `DJANGO_SECRET_KEY` mudou e invalidou tokens.

**Solução:**

```bash
make migrate
```

### `NoReverseMatch` ao acessar qualquer página em DEBUG

**Causa provável:** `debug_toolbar` está instalado mas URLs não registradas.

**Solução:** já tratado em [`core/urls.py`](../../core/urls.py); verifique se `debug_toolbar` está em `INSTALLED_APPS`.

## Problemas de webhooks

### Webhook do HubSpot retorna 401

**Causa provável:**

- `HUBSPOT_APP_SECRET` incorreto ou ausente.
- Assinatura v1/v3 não está sendo calculada corretamente.
- Endpoint de dev exposto sem `DEBUG=true`.

**Solução:**

- Confira o secret no portal do HubSpot.
- Use o simulador local com `USE_MOCK_HUBSPOT=True`.
- Verifique se o header `X-HubSpot-Signature-v3` está presente.

### Webhooks duplicados criam tickets duplicados

**Causa provável:** falha no Redis lock de deduplicação.

**Solução:**

- Verifique se `REDIS_URL` está acessível.
- Confira logs do Celery para `matchmaker_assign_single_dedup`.

## Problemas de Celery

### Tasks não são executadas

**Causa provável:**

- Worker não está rodando.
- Broker URL incorreta.
- Task não foi descoberta.

**Solução:**

```bash
celery -A core.celery inspect active
celery -A core.celery inspect scheduled
```

### `DatabaseLocked` ou `OperationalError` em SQLite

**Causa provável:** settings de teste usam SQLite? Não — testes usam PostgreSQL via `core.settings.test`. Verifique `DJANGO_SETTINGS_MODULE`.

**Solução:**

```bash
echo $env:DJANGO_SETTINGS_MODULE  # deve ser core.settings.test durante testes
```

### `mypy` não roda no CI / pre-commit

**Causa provável:** `mypy` é tooling obrigatório no `AGENTS.md`, mas não está configurado em `.pre-commit-config.yaml`, `Makefile`, `run.ps1` nem `.github/workflows/ci.yml`.

**Solução:** execute `mypy .` manualmente localmente ou configure-o nos scripts de qualidade.

## Problemas de IA

### `/api/v1/ai/` retorna 404

**Causa provável:** `AI_ROUTING_ENABLED` está `False`.

**Solução:** defina `AI_ROUTING_ENABLED=true` e reinicie a API.

### `PineconeException` no RAG

**Causa provável:**

- `PINECONE_API_KEY` ou `PINECONE_INDEX_NAME` ausentes.
- Índice não existe ou host incorreto.

**Solução:** verifique as variáveis e a existência do índice no console Pinecone.

### Agente responde "transbordo" para tudo

**Causa provável:**

- Circuit breaker de 15k tokens atingido.
- MCP server não conseguiu se conectar.

**Solução:**

- Verifique `TokenTrackingLog` para a sessão.
- Confira logs do MCP server.

## Problemas de deploy

### Railway retorna `DisallowedHost`

**Causa provável:** `ALLOWED_HOSTS` não inclui o domínio do Railway.

**Solução:** `core/settings/production.py` adiciona `.railway.app` e `RAILWAY_PUBLIC_DOMAIN` automaticamente.

### Health check do Railway falha

**Causa provável:**

- `SECURE_SSL_REDIRECT=True` causa redirect infinito.
- Banco de dados não responde.

**Solução:** `SECURE_SSL_REDIRECT` está desabilitado em produção; verifique `DATABASE_URL` e `REDIS_URL`.

## Arquivos relacionados

- [`setup/local-development.md`](./local-development.md)
- [`setup/environment-variables.md`](./environment-variables.md)
- [`setup/docker.md`](./docker.md)
- [`operations/monitoring.md`](../operations/monitoring.md)
- [`operations/logging.md`](../operations/logging.md)

## Pontos de atenção

- O `conftest.py` deleta dados de tabelas de suporte antes de cada teste. Nunca aponte `DATABASE_URL` para produção em testes.
- `DEBUG=True` desabilita verificações de webhook; use apenas localmente.

## Recomendações

- Sempre consulte logs estruturados com `request_id` para correlacionar erros.
- Use Sentry para rastrear exceções em staging/produção.
- Mantenha este documento atualizado com novos problemas encontrados.
