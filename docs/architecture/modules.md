# Módulos

| Módulo | Responsabilidade preservada |
|---|---|
| `apps/support` | agentes, SAT, calendário, filas, Matchmaker, atribuição, ciclos e métricas |
| `apps/webhooks` | autenticação, persistência, idempotência e dispatch operacional |
| `apps/ai_agents` | lifecycle genérico, ledger, watchdog e capacidades de IA independentes |
| `apps/integrations` | clientes HubSpot, Jira, Pinecone, Supabase e Salomão v1 |
| `apps/knowledge` | artigos e busca semântica |
| `apps/analytics` | relatórios operacionais |
| `apps/auth_user` | autenticação JWT e usuários |
| `apps/church` | igrejas e planos |
| `apps/health` | liveness e readiness |

`apps/ai_agents` não registra router HTTP e não contém identificador de cliente,
classificador de intenção, agente de triagem ou orquestrador Supervisor. Estados
genéricos de atendimento humano, IA independente, espera, resolução e falha
continuam disponíveis ao lifecycle.
