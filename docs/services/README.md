# Serviços e Módulos

## Resumo

Esta pasta documenta cada serviço/módulo do JUDAH: finalidade, responsabilidades, arquivos principais, endpoints, regras de negócio e pontos de manutenção.

## Lista de serviços

| Serviço | Descrição | Documentação |
|---------|-----------|--------------|
| `auth_user` | Autenticação e usuários | [`auth_user.md`](./auth_user.md) |
| `church` | Igrejas, planos e gateways | [`church.md`](./church.md) |
| `knowledge` | Base de conhecimento | [`knowledge.md`](./knowledge.md) |
| `support` | Tickets, filas, SAT, Matchmaker | [`support.md`](./support.md) |
| `ai_agents` | Agentes de IA (Salomão) | [`ai_agents.md`](./ai_agents.md) |
| `integrations` | Clients externos | [`integrations.md`](./integrations.md) |
| `webhooks` | Recebimento de webhooks | [`webhooks.md`](./webhooks.md) |
| `analytics` | Métricas e relatórios | [`analytics.md`](./analytics.md) |
| `health` | Health checks | [`health.md`](./health.md) |
| `webapp` | Frontend Next.js | [`webapp.md`](./webapp.md) |

## Cross-cutting concerns

Para módulos compartilhados (`common/`, `core/`), consulte [`architecture/modules.md`](../architecture/modules.md).
