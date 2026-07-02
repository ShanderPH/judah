> Início / [Visão geral](../README.md) / [Índice completo](../INDEX.md)

# Operações

## Resumo

Documentação operacional do JUDAH: deploy, monitoramento, logging e procedimentos de rollback.

## Conteúdo desta seção

| Documento | Descrição |
|-----------|-----------|
| [deployment.md](./deployment.md) | Fluxo de deploy no Railway |
| [monitoring.md](./monitoring.md) | Métricas, alertas e health checks |
| [logging.md](./logging.md) | Estrutura de logs e tracing |
| [rollback.md](./rollback.md) | Procedimentos de rollback |

## Infraestrutura de deploy

- Railway hospeda API, Celery Worker e Celery Beat.
- PostgreSQL 16 via Supabase.
- Redis 7 usado como broker e cache.
- Sentry para rastreamento de erros.

## Checklist pré-deploy

Ver [`AGENTS.md` §14](../../AGENTS.md#14-checklist-pré-deploy-deste-repo).
