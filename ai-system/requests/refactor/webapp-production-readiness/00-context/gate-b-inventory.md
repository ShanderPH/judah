# Gate B — inventário revalidado

Data: 2026-07-29. Base: `223ed5853bf1e2d159f02b1e99c6bde96b8d0660`.

- Três writes (`sync-novo`, criação e remoção de special schedule) desativavam o JWT global com `auth=None`.
- Leituras de agentes, métricas, time logs e reatribuições herdavam JWT sem contrato manager/admin.
- `require_role` aceitava identidade autenticada sem atributo `role`.
- `GET /auth/{user_id}` expunha outro perfil a qualquer identidade autenticada.
- `ToolCallAuditLog` é específico de ferramentas de IA; não existe ledger humano genérico reutilizável no escopo.
- O WebApp consome essas superfícies pelo BFF em `webapp/src/lib/api/client.ts`.

Health/webhooks e o ciclo público de autenticação foram preservados. Nenhum request externo, acesso a produção, HubSpot, Supabase ou banco não local foi executado.
