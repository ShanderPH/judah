# Endpoints

A API Django Ninja é publicada sob `/api/v1/`.

| Prefixo | Uso |
|---|---|
| `/auth/` | registro, login, refresh, logout e perfil |
| `/church/` | consulta de igrejas |
| `/knowledge/` | artigos e busca semântica |
| `/support/` | tickets, agentes, filas, calendário, atribuição e métricas |
| `/webhooks/` | HubSpot e Jira; sem autenticação JWT, com validação própria |
| `/analytics/` | relatórios operacionais |
| `/health/` | liveness e readiness |

Não existe router `/api/v1/ai/` nem endpoint de identificação, triagem ou
decisão de bot. A documentação OpenAPI em `/api/v1/docs` é a referência para os
schemas detalhados dos routers ativos.
