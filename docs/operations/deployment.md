> [Índice completo](../INDEX.md)

# Deploy

## Resumo

O JUDAH é implantado na Railway. Existem três serviços: API Django, Celery Worker e Celery Beat.

## Ambientes

| Ambiente | Branch | Banco | Uso |
|----------|--------|-------|-----|
| Produção | `production` | Supabase production | ambiente real |
| Staging | `main` | Supabase staging | validação pré-prod |
| Local | — | PostgreSQL local / Supabase dev | desenvolvimento |

## Fluxo de deploy

1. Merge na branch `main` dispara deploy em staging.
2. Validação de smoke tests e Sentry.
3. Pull request de `main` para `production`.
4. Merge em `production` dispara deploy em produção.

## Serviços Railway

```text
judah-api        → Django + Ninja (PORT 8000)
judah-worker     → Celery Worker
judah-beat       → Celery Beat
```

## Variáveis de ambiente

Todas definidas no Railway Dashboard ou via Antigravity Secrets. Ver [`setup/environment-variables.md`](../setup/environment-variables.md).

## Comandos de deploy

```bash
# Deploy em staging ocorre automaticamente no merge em main
# Deploy em produção requer merge em production
```

## Migrations em produção

1. Aplicar em staging primeiro.
2. Validar smoke tests.
3. Aplicar em produção via Railway CLI ou dashboard.

## Arquivos relacionados

- [`setup/environment-variables.md`](../setup/environment-variables.md)
- [`setup/docker.md`](../setup/docker.md)
