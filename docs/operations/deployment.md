> [Índice completo](../INDEX.md)

# Deploy

## Resumo

O JUDAH é implantado na Railway. Existem três serviços: API Django, Celery Worker e Celery Beat.

## Ambientes

| Ambiente | Branch / Trigger | Banco | Uso |
|----------|------------------|-------|-----|
| Produção | `main` + tag `v*.*.*` ou configuração manual no Railway | Supabase production | ambiente real |
| Staging | `main` | Supabase staging | validação pré-prod |
| Local | — | PostgreSQL local / Supabase dev | desenvolvimento |

## Fluxo de deploy

1. Merge na branch `main` ou push de tag `v*.*.*` dispara a pipeline de CI/CD (`.github/workflows/cd.yml`).
2. Validação de smoke tests e Sentry.
3. Deploy em produção no Railway (o `cd.yml` atual imprime placeholders; a integração real com o provider deve ser configurada no dashboard ou via CLI).

> **Nota:** o CI atual (`.github/workflows/cd.yml`) roda em push para `main` e tags `v*.*.*`, mas o step de deploy é um placeholder. Não há branch `production` protegida no workflow atual — o trigger é `main` ou tag.

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
